"""Programové rozhranie: anonymizácia a obnova súborov."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .config import Config
from .core import Planner, Report
from .detector import Detector
from .handlers import SUPPORTED, handler_for
from .pseudonymizer import Pseudonymizer
from .vault import Vault


def collect(inputs: list[str | Path]) -> list[Path]:
    files = []
    for item in map(Path, inputs):
        if item.is_dir():
            files += sorted(p for p in item.rglob("*") if p.suffix.lower() in SUPPORTED and p.is_file()
                            and not p.name.endswith(".report.json"))
        elif item.is_file():
            files.append(item)
        else:
            raise FileNotFoundError(item)
    return files


class Anonymizer:
    """Jedna inštancia = jeden beh; všetky súbory zdieľajú tokeny (rovnaká osoba = rovnaký token)."""

    def __init__(self, mode: str, cfg: Config | None = None, vault: Vault | None = None,
                 with_context: bool = False):
        self.with_context = with_context
        self.cfg = cfg or Config()
        self.mode = mode
        self.vault = vault if vault is not None else (Vault() if mode == "reversible" else None)
        self.detector = Detector(self.cfg)
        self.pseudo = Pseudonymizer(mode, self.vault if mode == "reversible" else None, self.cfg.numbered_tokens)

    progress = None   # callback(str) – priebeh pre UI

    def anonymize_bytes(self, data: bytes, name: str) -> tuple[bytes, Report]:
        handler = handler_for(name)
        if handler is None:
            raise ValueError(f"Nepodporovaný formát: {name}")
        report = Report(file=name, engine=self.detector.engine_name, mode=self.mode)
        planner = Planner(self.detector, self.pseudo, report=report,
                          vault=self.vault if self.mode == "reversible" else None, with_context=self.with_context)
        planner.progress = self.progress
        out = handler.process(data, planner, self.cfg, name=name)
        if self.mode == "reversible" and handler.__name__.endswith(".pdf"):
            self.vault.store_original(out, data)
        return out, report

    def anonymize_file(self, path: Path, out_dir: Path) -> tuple[Path, Report]:
        out_dir.mkdir(parents=True, exist_ok=True)
        out, report = self.anonymize_bytes(path.read_bytes(), path.name)
        target = out_dir / f"{path.stem}_anonym{path.suffix}"
        target.write_bytes(out)
        report_path = out_dir / f"{path.stem}_anonym.report.json"
        report_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=1), encoding="utf-8")
        return target, report

    def finish(self) -> None:
        self.pseudo.finish()


def restore_bytes(data: bytes, name: str, vault: Vault, cfg: Config | None = None) -> tuple[bytes, int]:
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        original = vault.get_original(data)
        if original is None:
            raise ValueError("Tento PDF súbor v trezore nie je (bol zmenený, alebo je z iného behu).")
        return original, -1
    handler = handler_for(name)
    if handler is None:
        raise ValueError(f"Nepodporovaný formát: {name}")
    report = Report()
    planner = Planner(restore_tokens=vault.data["tokens"], report=report, vault=vault)
    counter = {"n": 0}
    orig_plan = planner.plan

    def counting(segments, where="", joiners=None):
        res = orig_plan(segments, where, joiners)
        counter["n"] += sum(1 for reps in res for r in reps if r.token)
        return res

    planner.plan = counting
    return handler.process(data, planner, cfg or Config(), name=name), counter["n"]
