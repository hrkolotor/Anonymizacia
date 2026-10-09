"""Obyčajný text (TXT, MD, CSV, JSON)."""


def decode(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "cp1250", "iso-8859-2"):
        try:
            return data.decode(enc), ("utf-8" if enc == "utf-8-sig" else enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8"


def process(data: bytes, planner, cfg=None, name: str = "") -> bytes:
    text, enc = decode(data)
    lines = text.split("\n")
    per = planner.plan(lines, where="riadok")
    from ..core import apply

    out = "\n".join(apply(line, reps) for line, reps in zip(lines, per))
    return out.encode("utf-8" if enc in ("cp1250", "iso-8859-2") else enc)
