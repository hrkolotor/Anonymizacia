"""PDF - textové aj skenované.

Postup pre každú stranu:
  1. slová s pozíciami z textovej vrstvy (pdfplumber); ak strana nemá text alebo
     obsahuje obrázky, doplní sa OCR (tesseract) - zachytí aj naskenované prílohy,
  2. celý dokument sa analyzuje naraz, nálezy sa premietnu na súradnice slov,
  3. strana sa vyrenderuje do obrázka a nálezy sa prekryjú čiernym obdĺžnikom s tokenom,
  4. z obrázkov sa zloží nové PDF (voliteľne s OCR textovou vrstvou na vyhľadávanie).

Rasterizácia je zámerná: vo výstupe nezostanú skryté textové vrstvy, metadáta,
formulárové polia, anotácie ani prílohy, z ktorých by sa dal originál obnoviť.
Vratný režim ukladá originál PDF šifrovane do trezoru.
"""

from __future__ import annotations

import io
import logging
import os
from functools import lru_cache

import pdfplumber
import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter

log = logging.getLogger(__name__)
FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf"]


# ------------------------------------------------------------------ OCR jazyk
@lru_cache(maxsize=None)
def ocr_lang(requested: str) -> str:
    try:
        available = set(pytesseract.get_languages(config=""))
    except Exception:
        return "eng"
    langs = [lang for lang in requested.split("+") if lang in available]
    missing = [lang for lang in requested.split("+") if lang not in available]
    if missing:
        log.warning("Tesseract nemá jazyk(y) %s - nainštalujte ich (napr. tesseract-ocr-slk). "
                    "Rozpoznávanie funguje aj bez diakritiky, ale presnosť OCR bude nižšia.", missing)
    return "+".join(langs) or "eng"


# ------------------------------------------------------------------ slová strany
class Word:
    __slots__ = ("text", "x0", "top", "x1", "bottom", "line")

    def __init__(self, text, x0, top, x1, bottom, line=0):
        self.text, self.x0, self.top, self.x1, self.bottom, self.line = text, x0, top, x1, bottom, line


def _text_words(page) -> list[Word]:
    words = sorted(page.extract_words(keep_blank_chars=False, use_text_flow=False),
                   key=lambda w: (round(w["top"]), w["x0"]))
    out, line, last_top, last_h = [], -1, None, 0
    for w in words:
        h = w["bottom"] - w["top"]
        if last_top is None or abs(w["top"] - last_top) > max(h, last_h) * 0.5:
            line += 1
            last_top, last_h = w["top"], h
        out.append(Word(w["text"], w["x0"], w["top"], w["x1"], w["bottom"], line))
    out.sort(key=lambda w: (w.line, w.x0))
    return out


def _ocr_words(img: Image.Image, scale: float, lang: str, line_offset: int) -> list[Word]:
    d = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT, config="--psm 3")
    out, keys = [], {}
    for i, txt in enumerate(d["text"]):
        if not txt.strip() or float(d["conf"][i]) < 0:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        line = keys.setdefault(key, line_offset + len(keys))
        x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
        out.append(Word(txt, x / scale, y / scale, (x + w) / scale, (y + h) / scale, line))
    return out


def _intersects(a: Word, b: Word) -> bool:
    return a.x0 < b.x1 and b.x0 < a.x1 and a.top < b.bottom and b.top < a.bottom


def _page_text(words: list[Word]) -> tuple[str, list[tuple[int, int]]]:
    parts, ranges, pos, prev_line = [], [], 0, None
    for w in words:
        if prev_line is not None:
            sep = " " if w.line == prev_line else "\n"
            parts.append(sep)
            pos += 1
        ranges.append((pos, pos + len(w.text)))
        parts.append(w.text)
        pos += len(w.text)
        prev_line = w.line
    return "".join(parts), ranges


# ------------------------------------------------------------------ kreslenie
@lru_cache(maxsize=None)
def _font(size: int):
    for p in FONT_PATHS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _draw_box(draw: ImageDraw.ImageDraw, box, label: str):
    x0, y0, x1, y1 = box
    draw.rectangle(box, fill="black")
    if not label:
        return
    h = y1 - y0
    for size in range(max(6, int(h * 0.8)), 5, -1):
        f = _font(size)
        tw = draw.textlength(label, font=f)
        if tw <= (x1 - x0) - 2:
            draw.text((x0 + 1, y0 + (h - size) / 2 - 1), label, fill="white", font=f)
            return


# ------------------------------------------------------------------ hlavná funkcia
def process(data: bytes, planner, cfg, name: str = "") -> bytes:
    if planner.restoring:
        raise RuntimeError("PDF sa obnovuje z originálu uloženého v trezore (restore_pdf).")
    dpi, scale = cfg.pdf_dpi, cfg.pdf_dpi / 72.0
    lang = ocr_lang(cfg.ocr_lang)

    pages_words, images = [], []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for i, page in enumerate(pdf.pages):
            img = convert_from_bytes(data, dpi=dpi, first_page=i + 1, last_page=i + 1)[0].convert("RGB")
            words = _text_words(page) if cfg.pdf_ocr != "always" else []
            has_text = sum(len(w.text) for w in words) >= 20
            page_area = float(page.width * page.height) or 1.0
            img_area = sum(max(0, (im["x1"] - im["x0"]) * (im["bottom"] - im["top"])) for im in page.images)
            need_ocr = cfg.pdf_ocr == "always" or (cfg.pdf_ocr == "auto" and
                                                    (not has_text or img_area / page_area > 0.2))
            if need_ocr:
                start = (max((w.line for w in words), default=-1) + 1)
                ocr = [w for w in _ocr_words(img, scale, lang, start) if not any(_intersects(w, t) for t in words)]
                words = sorted(words + ocr, key=lambda w: (w.line, w.x0))
                if not has_text:
                    planner.report.warnings.append(f"{name}: strana {i + 1} spracovaná cez OCR ({lang}).")
            pages_words.append(words)
            images.append(img)

    texts, ranges = zip(*[_page_text(w) for w in pages_words]) if pages_words else ((), ())
    per_page = planner.plan(list(texts), where="strana")

    writer = PdfWriter()
    for words, rngs, reps, img in zip(pages_words, ranges, per_page, images):
        draw = ImageDraw.Draw(img)
        for r in reps:
            hit = [w for w, (s, e) in zip(words, rngs) if s < r.end and r.start < e]
            by_line: dict[int, list[Word]] = {}
            for w in hit:
                by_line.setdefault(w.line, []).append(w)
            for k, ws in enumerate(by_line.values()):
                pad = 1.5
                box = (min(w.x0 for w in ws) * scale - pad, min(w.top for w in ws) * scale - pad,
                       max(w.x1 for w in ws) * scale + pad, max(w.bottom for w in ws) * scale + pad)
                _draw_box(draw, box, r.token if k == 0 else "")
        _add_page(writer, img, dpi, lang if cfg.pdf_text_layer else None)

    out = io.BytesIO()
    writer.add_metadata({"/Producer": "anonymizer-sk"})
    writer.write(out)
    return out.getvalue()


def _add_page(writer: PdfWriter, img: Image.Image, dpi: int, lang: str | None):
    if lang:
        pdf_bytes = pytesseract.image_to_pdf_or_hocr(img, lang=lang, extension="pdf", config=f"--dpi {dpi}")
    else:
        buf = io.BytesIO()
        img.save(buf, format="PDF", resolution=dpi)
        pdf_bytes = buf.getvalue()
    for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
        writer.add_page(page)
