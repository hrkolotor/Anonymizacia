"""Úlohy webového rozhrania: nahrané súbory, kontrola nálezov, anonymizácia, obnova.

Všetko sa drží len v pamäti procesu. Nič sa nezapisuje na disk a pri ukončení
aplikácie (alebo po „Začať odznova“) sa obsah zahodí.
"""

from __future__ import annotations

import io
import threading
import time
import traceback
import uuid
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from ..api import Anonymizer, restore_bytes
from ..config import Config
from ..entities import ENTITY_LABELS
from ..handlers import SUPPORTED
from ..vault import Vault, VaultError

MAX_FILE = 200 * 1024 * 1024
LOW_SCORE = 0.75


class JobError(Exception):
    pass


class Job:
    def __init__(self, kind: str):
        self.id = uuid.uuid4().hex
        self.kind = kind                    # "anon" | "restore"
        self.files: dict[str, bytes] = {}
        self.vault_file: bytes | None = None
        self.state = "new"                  # new | working | scanned | done | error
        self.progress = ""
        self.error = ""
        self.groups: list[dict] = []
        self.warnings: list[str] = []
        self.summary: dict = {}
        self.result: bytes | None = None
        self.result_name = ""
        self.vault_out: bytes | None = None
        self.vault_name = ""
        self.touched = time.time()
        self.lock = threading.Lock()

    # ------------------------------------------------------------- súbory
    def add_file(self, name: str, data: bytes) -> str:
        name = Path(name.replace("\\", "/")).name or "subor"
        if len(data) > MAX_FILE:
            raise JobError(f"Súbor {name} je väčší ako 200 MB.")
        suffix = Path(name).suffix.lower()
        if self.kind == "restore" and suffix == ".vault":
            self.vault_file = data
            return name
        if suffix not in SUPPORTED:
            raise JobError(f"{name}: tento formát sa nedá spracovať. Podporované sú Word (.docx), PDF, "
                           f"e-maily (.eml) a text (.txt).")
        base, n = name, 2
        while name in self.files:
            name = f"{Path(base).stem} ({n}){Path(base).suffix}"
            n += 1
        self.files[name] = data
        self._reset()
        return name

    def remove_file(self, name: str):
        self.files.pop(name, None)
        self._reset()

    def _reset(self):
        self.state, self.groups, self.result, self.vault_out, self.summary = "new", [], None, None, {}

    # ------------------------------------------------------------- stav pre UI
    def status(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "state": self.state, "progress": self.progress, "error": self.error,
            "files": [{"name": n, "size": len(d)} for n, d in self.files.items()],
            "hasVault": self.vault_file is not None,
            "groups": self.groups, "warnings": self.warnings, "summary": self.summary,
            "result": bool(self.result), "resultName": self.result_name,
            "vault": bool(self.vault_out), "vaultName": self.vault_name,
        }

    def _run(self, fn, *args):
        if self.state == "working":
            raise JobError("Úloha už prebieha.")
        self.state, self.error, self.progress = "working", "", "Pripravujem…"

        def target():
            try:
                fn(*args)
            except (JobError, VaultError) as exc:
                self.state, self.error = "error", str(exc)
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self.state, self.error = "error", f"Nastala neočakávaná chyba: {exc}"
            finally:
                self.progress = ""
                self.touched = time.time()

        threading.Thread(target=target, daemon=True).start()

    # ------------------------------------------------------------- kontrola nálezov
    def start_scan(self, cfg: Config):
        if not self.files:
            raise JobError("Najprv pridajte dokumenty.")
        self._run(self._scan, cfg)

    def _scan(self, cfg: Config):
        anon = Anonymizer("reversible", cfg, with_context=True)
        anon.progress = lambda msg: setattr(self, "progress", msg)
        groups: dict[tuple, dict] = {}
        warnings = []
        n = len(self.files)
        for i, (name, data) in enumerate(self.files.items(), 1):
            self.progress = f"Hľadám osobné údaje: {name} ({i} z {n})"
            try:
                _, report = anon.anonymize_bytes(data, name)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{name}: súbor sa nepodarilo prečítať ({exc}).")
                continue
            warnings += report.warnings
            for f in report.findings:
                original = anon.pseudo.tokens.get(f["token"], "")
                base = f["token"].split("/")[0].rstrip("]") + "]"       # [OSOBA_001/3] -> [OSOBA_001]
                g = groups.get(base)
                if g is None:
                    g = groups[base] = {
                        "id": f"g{len(groups) + 1}", "entity": f["entity"],
                        "label": ENTITY_LABELS.get(f["entity"], f["entity"]), "text": original,
                        "variants": [], "token": base, "count": 0, "files": [], "score": 0.0,
                        "context": f.get("context"),
                    }
                if original not in g["variants"]:
                    g["variants"].append(original)
                g["count"] += 1
                g["score"] = max(g["score"], f["score"])
                if name not in g["files"]:
                    g["files"].append(name)
        order = {e: i for i, e in enumerate(ENTITY_LABELS)}
        self.groups = sorted(groups.values(), key=lambda g: (order.get(g["entity"], 99), int(g["id"][1:])))
        for g in self.groups:
            g["check"] = g["score"] < LOW_SCORE
            g["text"] = max(g["variants"], key=len)      # najúplnejší tvar (s titulom, celé meno)
            g["others"] = [v for v in g["variants"] if v != g["text"]]
        self.warnings = warnings
        self.state = "scanned"

    # ------------------------------------------------------------- anonymizácia
    def start_process(self, cfg: Config, mode: str, passphrase: str, excluded: list, added: list):
        if mode not in ("reversible", "irreversible"):
            raise JobError("Vyberte, či má byť anonymizácia vratná alebo trvalá.")
        if mode == "reversible" and len(passphrase or "") < 12:
            raise JobError("Heslo k trezoru musí mať aspoň 12 znakov.")
        by_id = {g["id"]: g for g in self.groups}
        cfg.allow_list = list(cfg.allow_list) + [v for i in excluded if i in by_id for v in by_id[i]["variants"]]
        cfg.deny_list = list(cfg.deny_list) + [
            {"text": a["text"].strip(), "entity": a.get("entity") or "VLASTNE"}
            for a in added if a.get("text", "").strip()]
        self._run(self._process, cfg, mode, passphrase)

    def _process(self, cfg: Config, mode: str, passphrase: str):
        anon = Anonymizer(mode, cfg)
        anon.progress = lambda msg: setattr(self, "progress", msg)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        buf, lines, totals = io.BytesIO(), [], Counter()
        warnings = []
        n = len(self.files)
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for i, (name, data) in enumerate(self.files.items(), 1):
                self.progress = f"Anonymizujem: {name} ({i} z {n})"
                try:
                    out, report = anon.anonymize_bytes(data, name)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"{name}: nespracované ({exc}).")
                    lines.append(f"{name}\n  NESPRACOVANÉ: {exc}\n")
                    continue
                p = Path(name)
                z.writestr(f"{p.stem}_anonym{p.suffix}", out)
                per = Counter(f["entity"] for f in report.findings)
                totals.update(per)
                warnings += report.warnings
                lines.append(f"{name}  ->  {p.stem}_anonym{p.suffix}")
                lines += [f"  {ENTITY_LABELS.get(e, e)}: {c}" for e, c in per.most_common()]
                lines += [f"  ! {w}" for w in report.warnings]
                lines.append("")
            head = [f"Anonymizácia dokumentov – {datetime.now():%d. %m. %Y %H:%M}",
                    "Režim: " + ("vratný (originály sa dajú obnoviť s trezorom a heslom)" if mode == "reversible"
                                 else "trvalý (originály sa nedajú obnoviť)"),
                    f"Spolu nahradených údajov: {sum(totals.values())}", ""]
            z.writestr("protokol.txt", "\n".join(head + lines))
        self.result, self.result_name = buf.getvalue(), f"anonymizovane_{stamp}.zip"
        if mode == "reversible":
            self.vault_out, self.vault_name = anon.vault.to_bytes(passphrase), f"trezor_{stamp}.vault"
        anon.finish()
        self.warnings = warnings
        self.summary = {"mode": mode, "total": sum(totals.values()), "files": n,
                        "byEntity": [{"label": ENTITY_LABELS.get(e, e), "count": c} for e, c in totals.most_common()]}
        self.state = "done"

    # ------------------------------------------------------------- obnova
    def start_restore(self, passphrase: str):
        if self.vault_file is None:
            raise JobError("Pridajte súbor trezoru (.vault), ktorý vznikol pri anonymizácii.")
        if not self.files:
            raise JobError("Pridajte anonymizované dokumenty, ktoré chcete obnoviť.")
        self._run(self._restore, passphrase)

    def _restore(self, passphrase: str):
        self.progress = "Otváram trezor…"
        vault = Vault.from_bytes(self.vault_file, passphrase)
        buf, done, warnings = io.BytesIO(), 0, []
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in self.files.items():
                self.progress = f"Obnovujem: {name}"
                try:
                    out, count = restore_bytes(data, name, vault)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"{name}: {exc}")
                    continue
                if count == 0:
                    warnings.append(f"{name}: neobsahuje žiadne údaje z tohto trezoru.")
                p = Path(name)
                z.writestr(f"{p.stem.removesuffix('_anonym')}_obnovene{p.suffix}", out)
                done += 1
        if done == 0:
            raise JobError("Žiadny dokument sa nepodarilo obnoviť. " + " ".join(warnings))
        self.result, self.result_name = buf.getvalue(), f"obnovene_{datetime.now():%Y-%m-%d_%H%M}.zip"
        self.warnings, self.summary, self.state = warnings, {"files": done}, "done"


class JobStore:
    def __init__(self):
        self.jobs: dict[str, Job] = {}

    def create(self, kind: str) -> Job:
        if kind not in ("anon", "restore"):
            raise JobError("Neznámy typ úlohy.")
        job = Job(kind)
        self.jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        job.touched = time.time()
        return job

    def delete(self, job_id: str):
        self.jobs.pop(job_id, None)

    def busy(self) -> bool:
        return any(j.state == "working" for j in self.jobs.values())
