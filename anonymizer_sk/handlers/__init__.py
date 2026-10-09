"""Spracovanie jednotlivých formátov. Každý handler má funkciu
process(data: bytes, planner: Planner, cfg: Config) -> bytes,
ktorá funguje pre anonymizáciu aj obnovu (podľa režimu planner-a)."""

from pathlib import Path

SUPPORTED = {".txt": "text", ".md": "text", ".csv": "text", ".json": "text", ".docx": "docx",
             ".pdf": "pdf", ".eml": "eml"}


def handler_for(name: str):
    kind = SUPPORTED.get(Path(name).suffix.lower())
    if kind is None:
        return None
    from importlib import import_module

    return import_module(f".{kind}", __name__)
