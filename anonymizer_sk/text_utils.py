"""Pomocné funkcie pre text."""

import re
import unicodedata
from functools import lru_cache


@lru_cache(maxsize=4096)
def _fold_char(c: str) -> str:
    base = unicodedata.normalize("NFD", c)[0]
    return base if len(base) == 1 else c


def fold(text: str) -> str:
    """Odstráni diakritiku znak po znaku. Dĺžka textu ostáva rovnaká,
    takže pozície nájdené vo výsledku platia aj v pôvodnom texte.
    Vďaka tomu rozpoznávače fungujú aj na OCR výstupe, ktorý stratil diakritiku."""
    return "".join(_fold_char(c) for c in text)


def norm_key(text: str) -> str:
    """Normalizovaný kľúč (bez diakritiky, malé písmená, len alfanumerické znaky)."""
    return re.sub(r"[\W_]+", "", fold(text).lower())


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


_FEMALE = ("ovej", "ovou", "ovu", "ova")
_SUFFIXES = ("ovia", "ovi", "eho", "emu", "ymi", "om", "ou", "ej", "ym", "a", "e", "u", "y", "i", "o")
_VOWEL_DROP = {"petr": "peter", "pavl": "pavol", "karl": "karol", "mark": "marek"}


def name_stem(word: str) -> str:
    """Približný kmeň slovenského mena, aby sa skloňované tvary
    (Novák, Nováka, Novákovi; Nováková, Novákovej) zlúčili do jednej osoby."""
    w = fold(word).lower().strip(".,")
    for suf in _FEMALE:
        if w.endswith(suf) and len(w) - len(suf) >= 2:
            return w[: -len(suf)] + "~f"
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)]
            break
    return _VOWEL_DROP.get(w, w)
