"""Detekčný pipeline: zdroje nálezov -> filtre -> riešenie prekryvov -> dohľadanie mien."""

from __future__ import annotations

import logging
import re

from .config import Config
from .rules import RuleDetector, Span
from .text_utils import fold, name_stem, norm_key

log = logging.getLogger(__name__)

TITLE_RE = re.compile(r"^(?:Ing|arch|Mgr|art|Bc|JUDr|MUDr|MDDr|MVDr|PhDr|RNDr|PaedDr|PharmDr|ThDr|ICDr|doc|prof|"
                      r"Dr|PhD|CSc|DrSc|MBA|LL|M|ArtD|MPH|DiS|pan|pani|p)\.?$", re.I)
CAP_WORD = re.compile(r"(?<![^\W\d_])[A-Z][^\W\d_]+(?![^\W\d_])")


def name_tokens(text: str) -> list[str]:
    """Slová mena bez titulov."""
    toks = re.findall(r"[^\W\d_]+(?:\.)?", fold(text))
    return [t.rstrip(".") for t in toks if not TITLE_RE.match(t) and t[:1].isupper() and len(t) > 1]


def surname_stems(name: str) -> set:
    toks = name_tokens(name)
    return {name_stem(t) for t in (toks[1:] if len(toks) > 1 else toks) if len(t) >= 3}


def _merge_same_entity(spans: list[Span]) -> list[Span]:
    """Prekrývajúce sa nálezy rovnakého typu zlúči do jedného (zjednotenie)."""
    out: list[Span] = []
    for sp in sorted(spans, key=lambda x: (x.entity, x.start)):
        if out and out[-1].entity == sp.entity and sp.start < out[-1].end:
            last = out[-1]
            last.end = max(last.end, sp.end)
            last.score = max(last.score, sp.score)
            if sp.source not in last.source.split("+"):
                last.source += "+" + sp.source
        else:
            out.append(Span(sp.start, sp.end, sp.entity, sp.score, sp.source))
    return out


def resolve(spans: list[Span]) -> list[Span]:
    spans = _merge_same_entity(spans)
    chosen: list[Span] = []
    for sp in sorted(spans, key=lambda x: (-x.score, -len(x), x.start)):
        if not any(sp.overlaps(c) for c in chosen):
            chosen.append(sp)
    return sorted(chosen, key=lambda x: x.start)


class Detector:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.sources = self._build_sources()
        self._allow = {norm_key(a) for a in self.cfg.allow_list}
        self._deny = [(re.compile(r"(?<![^\W\d_])" + re.escape(fold(d["text"])) + r"(?![^\W\d_])", re.I),
                       d.get("entity", "VLASTNE")) for d in self.cfg.deny_list]

    # ------------------------------------------------------------- zdroje
    def _build_sources(self):
        engine = self.cfg.engine
        if engine in ("auto", "presidio"):
            try:
                from .presidio_engine import PresidioDetector

                det = PresidioDetector(self.cfg)
                self.engine_name = "presidio" + ("+ner" if det.has_ner else "")
                return [det]
            except ImportError as exc:
                if engine == "presidio":
                    raise RuntimeError("Presidio nie je nainštalované: pip install -r requirements.txt") from exc
                log.warning("Presidio nie je k dispozícii (%s), používam slovenské pravidlá bez NER.", exc)
        sources = [RuleDetector()]
        self.engine_name = "rules"
        if engine == "rules+ner":
            from .ner import NerDetector

            sources.append(NerDetector(self.cfg.ner_model))
            self.engine_name = "rules+ner"
        return sources

    # ------------------------------------------------------------- detekcia
    def detect(self, text: str, known_stems: set | None = None) -> list[Span]:
        if not text.strip():
            return []
        folded = fold(text)
        spans: list[Span] = []
        for src in self.sources:
            spans.extend(src.raw_spans(text))
        for rx, entity in self._deny:
            spans.extend(Span(m.start(), m.end(), entity, 1.0, "deny_list") for m in rx.finditer(folded))
        spans = [s for s in spans if s.entity in self.cfg.entities or s.source == "deny_list"]
        spans = [s for s in spans if s.score >= self.cfg.threshold]
        spans = [s for s in spans if norm_key(text[s.start:s.end]) not in self._allow]
        spans = resolve(spans)
        if self.cfg.propagate_names and "OSOBA" in self.cfg.entities:
            spans = resolve(spans + self._propagate(text, folded, spans, known_stems or set()))
        for s in spans:
            s.text = text[s.start:s.end]
        return spans

    def _propagate(self, text: str, folded: str, spans: list[Span], known: set) -> list[Span]:
        """Priezvisko nájdené raz (napr. 'Ján Novák') dohľadá aj v ďalších tvaroch
        ('Nováka', 'pán Novák') kdekoľvek v dokumente. known = priezviská nájdené
        skôr v tom istom behu (iné časti e-mailu, iné súbory, existujúci trezor)."""
        stems = set(known)
        for sp in spans:
            if sp.entity == "OSOBA":
                stems |= surname_stems(text[sp.start:sp.end])
        if not stems:
            return []
        found = []
        for m in CAP_WORD.finditer(folded):
            word = m.group()
            if word.upper() == word:          # skratky typu "SNP"
                continue
            if name_stem(word) in stems and norm_key(text[m.start():m.end()]) not in self._allow:
                found.append(Span(m.start(), m.end(), "OSOBA", 0.7, "propagacia"))
        return found
