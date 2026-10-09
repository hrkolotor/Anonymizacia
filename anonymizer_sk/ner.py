"""NER model (predvolene SlovakBERT doladený na mená, organizácie a lokality).

Vyžaduje: pip install transformers torch
Model sa pri prvom spustení stiahne z Hugging Face; potom beží lokálne.
"""

from __future__ import annotations

import re

from .rules import Span

_LABEL_IDS = {1: "OSOBA", 2: "OSOBA", 3: "ORGANIZACIA", 4: "ORGANIZACIA", 5: "LOKALITA", 6: "LOKALITA"}


def map_label(label: str) -> str | None:
    lbl = re.sub(r"^[BIES]-", "", label.upper())
    if lbl.startswith("LABEL_"):
        return _LABEL_IDS.get(int(lbl[6:]))
    if "PER" in lbl or "OSOB" in lbl:
        return "OSOBA"
    if "ORG" in lbl:
        return "ORGANIZACIA"
    if "LOC" in lbl or "LOK" in lbl or "GPE" in lbl:
        return "LOKALITA"
    return None


def chunks(text: str, size: int = 1200):
    """Rozdelí text na kúsky do ~size znakov na hraniciach riadkov (limit modelu 512 tokenov)."""
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind("\n", start, end)
            if cut <= start:
                cut = text.rfind(" ", start, end)
            end = cut + 1 if cut > start else end
        yield start, text[start:end]
        start = end


class NerDetector:
    def __init__(self, model_name: str = "crabz/slovakbert-ner", min_score: float = 0.6):
        from transformers import pipeline

        self.pipe = pipeline("token-classification", model=model_name, aggregation_strategy="simple")
        self.min_score = min_score

    def raw_spans(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for offset, chunk in chunks(text):
            for r in self.pipe(chunk):
                entity = map_label(r.get("entity_group") or r.get("entity", ""))
                if not entity or float(r["score"]) < self.min_score:
                    continue
                spans.append(Span(offset + r["start"], offset + r["end"], entity, float(r["score"]), "ner"))
        return self._merge_adjacent(text, spans)

    @staticmethod
    def _merge_adjacent(text: str, spans: list[Span]) -> list[Span]:
        """Model s labelmi LABEL_n nevie spojiť B- a I- token; spojíme susedné rovnaké entity."""
        out: list[Span] = []
        for sp in sorted(spans, key=lambda s: s.start):
            if out and out[-1].entity == sp.entity and text[out[-1].end:sp.start].strip(" -") == "":
                out[-1].end = sp.end
                out[-1].score = (out[-1].score + sp.score) / 2
            else:
                out.append(sp)
        for sp in out:
            sp.score = round(sp.score, 3)
        return out
