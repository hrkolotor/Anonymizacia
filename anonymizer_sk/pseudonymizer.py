"""Prideľovanie náhradných tokenov.

Vratný režim:  každá entita dostane číslo ([OSOBA_001]); rôzne gramatické tvary tej
               istej osoby dostanú variant ([OSOBA_001/2]), aby sa dali presne vrátiť.
               Mapovanie sa ukladá do šifrovaného trezoru.
Trvalý režim:  [OSOBA_001] (alebo len [OSOBA]), nič sa neukladá - originál sa nedá obnoviť.
"""

from __future__ import annotations

import re

from .detector import name_tokens, surname_stems
from .rules import Span
from .text_utils import digits, name_stem, norm_key
from .vault import Vault

TOKEN_RE = re.compile(r"\[([A-Z_]+?)_(\d{3,})(?:/(\d+))?\]")
NUMERIC = {"RODNE_CISLO", "TELEFON", "IBAN", "UCET", "KARTA", "ICO", "DIC", "IC_DPH"}


def entity_key(sp: Span) -> frozenset:
    if sp.entity == "OSOBA":
        stems = {name_stem(t) for t in name_tokens(sp.text)}
        return frozenset(stems) if stems else frozenset({norm_key(sp.text)})
    if sp.entity in NUMERIC:
        return frozenset({digits(sp.text)[-9:] if sp.entity == "TELEFON" else digits(sp.text)})
    return frozenset({norm_key(sp.text)})


class Pseudonymizer:
    def __init__(self, mode: str, vault: Vault | None = None, numbered: bool = True):
        if mode not in ("reversible", "irreversible"):
            raise ValueError("mode musí byť 'reversible' alebo 'irreversible'")
        self.mode = mode
        self.numbered = numbered or mode == "reversible"
        self.vault = vault if vault is not None else Vault()
        d = self.vault.data
        self.tokens: dict = d["tokens"]
        self.counters: dict = d["counters"]
        # clusters: {entity: [{"id": n, "keys": [[...]], "variants": [surface, ...]}]}
        self.clusters: dict = d["clusters"]

    # ----------------------------------------------------------------- zhluky
    def _find_cluster(self, entity: str, key: frozenset):
        cands = []
        for cl in self.clusters.get(entity, []):
            keys = [frozenset(k) for k in cl["keys"]]
            if key in keys:
                return cl
            if entity == "OSOBA" and any(key <= k or k <= key for k in keys):
                cands.append(cl)
        return cands[0] if len(cands) == 1 else None

    def _cluster(self, sp: Span) -> dict:
        key = entity_key(sp)
        cl = self._find_cluster(sp.entity, key)
        if cl is None:
            n = self.counters.get(sp.entity, 0) + 1
            self.counters[sp.entity] = n
            cl = {"id": n, "keys": [sorted(key)], "variants": []}
            self.clusters.setdefault(sp.entity, []).append(cl)
        elif sorted(key) not in cl["keys"]:
            cl["keys"].append(sorted(key))
        if sp.entity == "OSOBA":
            cl["surnames"] = sorted(set(cl.get("surnames", [])) | surname_stems(sp.text))
        return cl

    def known_surnames(self) -> set:
        return {s for cl in self.clusters.get("OSOBA", []) for s in cl.get("surnames", [])}

    # ----------------------------------------------------------------- tokeny
    def assign(self, spans: list[Span]) -> dict[int, str]:
        """Vráti {id(span): token}. Osoby s celým menom sa spracujú skôr,
        aby sa samostatné priezviská priradili k správnej osobe."""
        order = sorted(spans, key=lambda s: (s.entity != "OSOBA", -len(entity_key(s)), s.start))
        clusters = {id(sp): self._cluster(sp) for sp in order}
        out = {}
        for sp in spans:
            cl = clusters[id(sp)]
            base = f"{sp.entity}_{cl['id']:03d}"
            if self.mode == "irreversible":
                out[id(sp)] = f"[{base}]" if self.numbered else f"[{sp.entity}]"
                continue
            if sp.text not in cl["variants"]:
                cl["variants"].append(sp.text)
            idx = cl["variants"].index(sp.text)
            token = f"[{base}]" if idx == 0 else f"[{base}/{idx + 1}]"
            self.tokens[token] = sp.text
            out[id(sp)] = token
        return out

    def finish(self) -> None:
        """V trvalom režime nesmie v pamäti ostať mapovanie."""
        if self.mode == "irreversible":
            for cl_list in self.clusters.values():
                for cl in cl_list:
                    cl["variants"].clear()
            self.tokens.clear()


def restore_text(text: str, tokens: dict) -> tuple[str, int]:
    count = 0

    def repl(m):
        nonlocal count
        orig = tokens.get(m.group(0))
        if orig is None:
            return m.group(0)
        count += 1
        return orig

    return TOKEN_RE.sub(repl, text), count
