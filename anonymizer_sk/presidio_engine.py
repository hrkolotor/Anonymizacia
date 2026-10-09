"""Napojenie na Presidio Analyzer.

Presidio tu slúži ako orchestrácia: register rozpoznávačov, spoločné API, skóre
a možnosť pridávať ďalšie rozpoznávače (napr. GLiNER, vlastné modely, firemné zoznamy).
Vstavané rozpoznávače Presidia sú anglické, preto pre jazyk "sk" registrujeme:
  * SlovakRulesRecognizer - slovenské pravidlá z rules.py (RČ, IČO, IBAN, adresy, mená ...)
  * SlovakNerRecognizer   - NER model (ak je nainštalovaný transformers)

Presidio vyžaduje NLP engine; slovenský spaCy model neexistuje, preto použijeme
prázdny spaCy pipeline "sk" (len tokenizácia). Kontextové vylepšenie skóre robia
priamo slovenské pravidlá (Presidio enhancer potrebuje lemy, ktoré nemáme).

POZOR: tento modul nebol spustený v prostredí, kde vznikal (Presidio nebolo možné
nainštalovať). Overte ho príkazom:  python -m anonymizer_sk selftest --engine presidio
"""

from __future__ import annotations

import logging
from pathlib import Path

from presidio_analyzer import AnalyzerEngine, EntityRecognizer, RecognizerRegistry, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider

from .config import Config
from .entities import ALL_ENTITIES
from .rules import RuleDetector, Span

log = logging.getLogger(__name__)
LANG = "sk"
BLANK_MODEL_DIR = Path.home() / ".cache" / "anonymizer_sk" / "spacy_sk_blank"


class SlovakRulesRecognizer(EntityRecognizer):
    def __init__(self):
        self._rules = RuleDetector()
        super().__init__(supported_entities=ALL_ENTITIES, supported_language=LANG, name="SlovakRulesRecognizer")

    def load(self) -> None:  # pravidlá netreba načítavať
        pass

    def analyze(self, text, entities, nlp_artifacts=None):
        return [RecognizerResult(s.entity, s.start, s.end, s.score,
                                 analysis_explanation=None, recognition_metadata={"source": s.source,
                                 RecognizerResult.RECOGNIZER_NAME_KEY: self.name})
                for s in self._rules.raw_spans(text) if not entities or s.entity in entities]


class SlovakNerRecognizer(EntityRecognizer):
    def __init__(self, model_name: str):
        from .ner import NerDetector

        self._ner = NerDetector(model_name)
        super().__init__(supported_entities=["OSOBA", "ORGANIZACIA", "LOKALITA"], supported_language=LANG,
                         name="SlovakNerRecognizer")

    def load(self) -> None:
        pass

    def analyze(self, text, entities, nlp_artifacts=None):
        return [RecognizerResult(s.entity, s.start, s.end, s.score,
                                 recognition_metadata={"source": "ner",
                                                       RecognizerResult.RECOGNIZER_NAME_KEY: self.name})
                for s in self._ner.raw_spans(text) if not entities or s.entity in entities]


def _blank_spacy_model() -> str:
    if not (BLANK_MODEL_DIR / "config.cfg").exists():
        import spacy

        BLANK_MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
        spacy.blank(LANG).to_disk(BLANK_MODEL_DIR)
    return str(BLANK_MODEL_DIR)


class PresidioDetector:
    def __init__(self, cfg: Config):
        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": LANG, "model_name": _blank_spacy_model()}],
        })
        registry = RecognizerRegistry(supported_languages=[LANG])
        registry.add_recognizer(SlovakRulesRecognizer())
        self.has_ner = False
        try:
            registry.add_recognizer(SlovakNerRecognizer(cfg.ner_model))
            self.has_ner = True
        except Exception as exc:  # transformers chýba alebo sa model nedá stiahnuť
            log.warning("NER model nie je k dispozícii (%s); mená sa hľadajú len pravidlami.", exc)
        self.analyzer = AnalyzerEngine(nlp_engine=provider.create_engine(), registry=registry,
                                       supported_languages=[LANG])

    def raw_spans(self, text: str) -> list[Span]:
        results = self.analyzer.analyze(text=text, language=LANG, score_threshold=0.0)
        return [Span(r.start, r.end, r.entity_type, float(r.score),
                     (r.recognition_metadata or {}).get("source", "presidio")) for r in results]
