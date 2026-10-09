"""Konfigurácia (predvolené hodnoty + voliteľný config.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .entities import ALL_ENTITIES, DEFAULT_DISABLED


@dataclass
class Config:
    threshold: float = 0.5
    entities: set = field(default_factory=lambda: set(ALL_ENTITIES) - DEFAULT_DISABLED)
    allow_list: list = field(default_factory=list)       # výrazy, ktoré sa nikdy neanonymizujú
    deny_list: list = field(default_factory=list)        # [{"text": "...", "entity": "OSOBA"}] vždy anonymizovať
    engine: str = "auto"                                 # auto | presidio | rules | rules+ner
    ner_model: str = "crabz/slovakbert-ner"
    ocr_lang: str = "slk+eng"
    pdf_dpi: int = 200
    pdf_ocr: str = "auto"                                # auto | always | never
    pdf_text_layer: bool = True                          # OCR textová vrstva vo výstupnom PDF
    numbered_tokens: bool = True                         # [OSOBA_001] vs. [OSOBA] (len trvalý režim)
    propagate_names: bool = True                         # dohľadať ďalšie výskyty priezvisk

    @classmethod
    def load(cls, path: str | Path | None) -> "Config":
        cfg = cls()
        if not path:
            return cfg
        import yaml

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        for key, value in data.items():
            if key == "entities":
                enabled = set(value.get("enabled", cfg.entities)) if isinstance(value, dict) else set(value)
                if isinstance(value, dict):
                    enabled |= set(value.get("enable", []))
                    enabled -= set(value.get("disable", []))
                cfg.entities = enabled
            elif key == "deny_list":
                cfg.deny_list = [d if isinstance(d, dict) else {"text": d, "entity": "VLASTNE"} for d in value]
            elif hasattr(cfg, key):
                setattr(cfg, key, value)
            else:
                raise ValueError(f"Neznámy kľúč v konfigurácii: {key}")
        return cfg
