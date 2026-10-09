"""Spoločná logika: text rozdelený na segmenty (odseky, uzly HTML, strany PDF)
sa analyzuje naraz, aby kontext a dohľadávanie mien fungovali naprieč celým
dokumentom, a výsledné náhrady sa premietnu späť do jednotlivých segmentov."""

from __future__ import annotations

from dataclasses import dataclass, field

from .detector import Detector
from .pseudonymizer import TOKEN_RE, Pseudonymizer

SEP = "\n"


@dataclass
class Replacement:
    start: int          # lokálne v rámci segmentu
    end: int
    token: str          # pri rozdelenom náleze dostane token len prvá časť, ostatné ""
    entity: str = ""
    score: float = 0.0
    source: str = ""
    original: str = ""


@dataclass
class Report:
    file: str = ""
    engine: str = ""
    mode: str = ""
    findings: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def add(self, where: str, r: Replacement):
        self.findings.append({"where": where, "entity": r.entity, "score": r.score, "source": r.source,
                              "token": r.token})


def _join(segments: list[str], joiners: list[str] | None = None):
    """joiners[i] = oddeľovač za segmentom i (predvolene nový riadok)."""
    joiners = joiners or [SEP] * len(segments)
    offsets, pos, parts = [], 0, []
    for seg, j in zip(segments, joiners):
        offsets.append(pos)
        parts += [seg, j]
        pos += len(seg) + len(j)
    return "".join(parts), offsets


def _split(spans_global, segments, offsets, tokens_for):
    """Rozdelí globálne nálezy na lokálne náhrady v segmentoch."""
    per_seg: list[list[Replacement]] = [[] for _ in segments]
    for sp in spans_global:
        tok = tokens_for(sp)
        first = True
        for i, (seg, off) in enumerate(zip(segments, offsets)):
            s, e = max(sp.start, off), min(sp.end, off + len(seg))
            if s >= e:
                continue
            per_seg[i].append(Replacement(s - off, e - off, tok if first else "", sp.entity,
                                          sp.score, sp.source, seg[s - off:e - off]))
            first = False
    return per_seg


def plan_anonymize(segments: list[str], detector: Detector, pseudo: Pseudonymizer, joiners=None):
    text, offsets = _join(segments, joiners)
    spans = detector.detect(text, pseudo.known_surnames())
    tokens = pseudo.assign(spans)
    return _split(spans, segments, offsets, lambda sp: tokens[id(sp)])


def plan_restore(segments: list[str], tokens: dict, joiners=None):
    text, offsets = _join(segments, joiners)

    class _S:
        def __init__(self, m):
            self.start, self.end, self.entity, self.score, self.source = m.start(), m.end(), "TOKEN", 1.0, "vault"
            self.token = tokens[m.group(0)]

    spans = [_S(m) for m in TOKEN_RE.finditer(text) if m.group(0) in tokens]
    return _split(spans, segments, offsets, lambda sp: sp.token)


def apply(text: str, reps: list[Replacement]) -> str:
    for r in sorted(reps, key=lambda r: r.start, reverse=True):
        text = text[:r.start] + r.token + text[r.end:]
    return text


class Planner:
    """Zabalí režim (anonymizácia / obnova), aby handlery formátov boli spoločné."""

    def __init__(self, detector: Detector | None = None, pseudo: Pseudonymizer | None = None,
                 restore_tokens: dict | None = None, report: Report | None = None, vault=None):
        self.detector, self.pseudo, self.restore_tokens = detector, pseudo, restore_tokens
        self.vault = vault
        self.report = report or Report()

    @property
    def restoring(self) -> bool:
        return self.restore_tokens is not None

    def plan(self, segments: list[str], where: str = "", joiners=None) -> list[list[Replacement]]:
        if self.restoring:
            return plan_restore(segments, self.restore_tokens, joiners)
        per_seg = plan_anonymize(segments, self.detector, self.pseudo, joiners)
        for i, reps in enumerate(per_seg):
            for r in reps:
                if r.token:
                    self.report.add(f"{where}#{i}" if where else str(i), r)
        return per_seg

    def text(self, value: str, where: str = "") -> str:
        return apply(value, self.plan([value], where)[0])

    def filename(self, value: str) -> str:
        """Názov súboru: oddeľovače _ - . sa pri detekcii považujú za medzery."""
        import re

        if self.restoring:
            return self.text(value, "nazov_suboru")
        probe = re.sub(r"[_\-.]", " ", value)
        reps = self.plan([probe], "nazov_suboru")[0]
        return apply(value, reps)
