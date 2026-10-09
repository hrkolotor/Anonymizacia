"""Cesty k pribaleným nástrojom (Tesseract, Poppler) a k dátovému priečinku aplikácie.

V zostavenom .exe (PyInstaller) sú nástroje vedľa programu:
    <app>/tools/tesseract/tesseract.exe + tessdata/
    <app>/tools/poppler/bin/pdftoppm.exe
Mimo .exe sa použijú nástroje z PATH, prípadne z premenných
ANONYMIZER_TESSERACT (cesta k tesseract.exe) a ANONYMIZER_POPPLER (priečinok bin).
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Priečinok na log a nastavenia (nikdy nie na dokumenty)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), ".local", "share")
    d = Path(base) / "anonymizer-sk"
    d.mkdir(parents=True, exist_ok=True)
    return d


@lru_cache(maxsize=None)
def configure() -> dict:
    """Nastaví pytesseract a vráti kwargs pre pdf2image (poppler_path)."""
    import pytesseract

    tools = app_dir() / "tools"
    tess = os.environ.get("ANONYMIZER_TESSERACT")
    if not tess:
        cand = tools / "tesseract" / ("tesseract.exe" if os.name == "nt" else "tesseract")
        tess = str(cand) if cand.exists() else None
    if tess:
        pytesseract.pytesseract.tesseract_cmd = tess
        tessdata = Path(tess).parent / "tessdata"
        if tessdata.exists():
            os.environ.setdefault("TESSDATA_PREFIX", str(tessdata))

    poppler = os.environ.get("ANONYMIZER_POPPLER")
    if not poppler and (tools / "poppler" / "bin").exists():
        poppler = str(tools / "poppler" / "bin")
    return {"poppler_path": poppler} if poppler else {}
