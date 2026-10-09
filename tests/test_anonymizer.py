"""Testy: validátory, detekcia, oba režimy na všetkých formátoch, obnova z trezoru.

Spustenie:  python tests/test_anonymizer.py      (alebo pytest tests/)
"""

from __future__ import annotations

import email
import io
import re
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import make_samples as M  # noqa: E402
from anonymizer_sk import validators as V  # noqa: E402
from anonymizer_sk.api import Anonymizer, restore_bytes  # noqa: E402
from anonymizer_sk.config import Config  # noqa: E402
from anonymizer_sk.detector import Detector  # noqa: E402
from anonymizer_sk.text_utils import fold  # noqa: E402
from anonymizer_sk.vault import Vault, VaultError  # noqa: E402

ENGINE = "rules"
_SAMPLES = None


def samples() -> Path:
    global _SAMPLES
    if _SAMPLES is None:
        _SAMPLES = Path(tempfile.mkdtemp(prefix="anon_samples_"))
        M.main(_SAMPLES)
    return _SAMPLES


# ------------------------------------------------------------------ extrakcia textu z výstupov
def text_of(data: bytes, name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix == ".txt":
        return data.decode("utf-8")
    if suffix == ".docx":
        z = zipfile.ZipFile(io.BytesIO(data))
        return "\n".join(re.sub(r"<[^>]+>", "", z.read(n).decode("utf-8")) for n in z.namelist()
                         if n.endswith(".xml") or n.endswith(".rels"))
    if suffix == ".eml":
        msg = email.message_from_bytes(data)
        out = [f"{k}: {v}" for k, v in msg.items()]
        for part in msg.walk():
            if part.is_multipart():
                continue
            payload = part.get_payload(decode=True) or b""
            fn = part.get_filename() or ""
            out.append(fn)
            if part.get_content_maintype() == "text":
                out.append(payload.decode("utf-8", "replace"))
            elif fn.endswith(".docx"):
                out.append(text_of(payload, fn))
        return "\n".join(out)
    if suffix == ".pdf":
        import pytesseract
        from pdf2image import convert_from_bytes
        from pypdf import PdfReader

        layer = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
        ocr = "\n".join(pytesseract.image_to_string(im) for im in convert_from_bytes(data, dpi=200))
        return layer + "\n" + ocr
    raise ValueError(name)


def leaked(text: str) -> list[str]:
    """Hľadá originály vrátane tvarov bez diakritiky a bez medzier (OCR)."""
    flat = re.sub(r"\s+", "", fold(text)).lower()
    hits = []
    for value in M.PII["osoby"] + M.PII["hodnoty"]:
        probe = re.sub(r"\s+", "", fold(value)).lower()
        if probe in flat:
            hits.append(value)
    return hits


# ------------------------------------------------------------------ validátory
def test_validators():
    assert V.rodne_cislo(M.RC1) and V.rodne_cislo(M.RC2)
    assert not V.rodne_cislo("800315/1234")
    assert not V.rodne_cislo("801332/1234")          # neplatný mesiac
    assert V.rodne_cislo("536231/123")              # 9-miestne do 1953
    assert V.ico(M.ICO1) and not V.ico("35757443")
    assert V.ic_dph(M.ICDPH1[2:])
    assert V.iban(M.IBAN1) and not V.iban(M.IBAN1.replace("1100", "1101"))
    assert V.luhn("4111 1111 1111 1111") and not V.luhn("4111 1111 1111 1112")


def test_detection_basics():
    det = Detector(Config(engine=ENGINE))
    text = ("Predávajúci: Ing. Ján Novák, nar. 15. 3. 1980, r. č. %s, trvalý pobyt: Hlavná 12, 811 01 "
            "Bratislava. Telefonovala pani Kováčová (0905 123 456). Úver vybavil Jozefovi Malému." % M.RC1)
    found = {(s.entity, s.text) for s in det.detect(text)}
    for item in [("OSOBA", "Ing. Ján Novák"), ("DATUM_NARODENIA", "15. 3. 1980"), ("RODNE_CISLO", M.RC1),
                 ("ADRESA", "Hlavná 12, 811 01 Bratislava"), ("OSOBA", "Kováčová"),
                 ("TELEFON", "0905 123 456"), ("OSOBA", "Jozefovi Malému")]:
        assert item in found, (item, found)


def test_no_false_positives_on_plain_text():
    det = Detector(Config(engine=ENGINE))
    text = ("Zmluva nadobúda platnosť dňom 1. 1. 2026 podľa § 588 Občianskeho zákonníka. Cena je 12 500 EUR "
            "a splatná je do 30 dní. Článok 3 ods. 2 sa uplatní primerane. Sídlo súdu je v Bratislave.")
    assert det.detect(text) == [], det.detect(text)


def test_allow_and_deny_list():
    cfg = Config(engine=ENGINE, allow_list=["Ján Novák"], deny_list=[{"text": "Projekt Orol", "entity": "VLASTNE"}])
    spans = Detector(cfg).detect("Konateľ: Ján Novák. Interný názov: Projekt Orol.")
    assert [(s.entity, s.text) for s in spans] == [("VLASTNE", "Projekt Orol")], spans


def test_vault_wrong_password():
    v = Vault()
    v.data["tokens"]["[OSOBA_001]"] = "Ján Novák"
    path = Path(tempfile.mkdtemp()) / "t.vault"
    v.save(path, "spravne-heslo-123")
    assert "Ján Novák" not in path.read_text()
    assert Vault.open(path, "spravne-heslo-123").data["tokens"]["[OSOBA_001]"] == "Ján Novák"
    try:
        Vault.open(path, "zle-heslo-12345")
        raise AssertionError("trezor sa otvoril so zlým heslom")
    except VaultError:
        pass


def _run(mode: str):
    anon = Anonymizer(mode, Config(engine=ENGINE))
    out = {}
    for path in sorted(samples().iterdir()):
        data, report = anon.anonymize_bytes(path.read_bytes(), path.name)
        out[path.name] = (data, report)
    anon.finish()
    return anon, out


def test_irreversible_all_formats():
    anon, out = _run("irreversible")
    assert anon.vault is None and not anon.pseudo.tokens
    for name, (data, report) in out.items():
        hits = leaked(text_of(data, name))
        assert not hits, f"{name}: zostali osobné údaje {hits}"
        assert report.findings, name
    eml = email.message_from_bytes(out["email.eml"][0])
    assert eml["Received"] is None and eml["X-Originating-IP"] is None
    assert not any(p.get_content_type() == "image/png" for p in eml.walk())


def test_reversible_roundtrip():
    anon, out = _run("reversible")
    path = Path(tempfile.mkdtemp()) / "trezor.vault"
    anon.vault.save(path, "testovacie-heslo-123")
    vault = Vault.open(path, "testovacie-heslo-123")
    for name, (data, _) in out.items():
        assert not leaked(text_of(data, name)), name
        restored, _ = restore_bytes(data, name, vault)
        original = (samples() / name).read_bytes()
        if name.endswith(".pdf"):
            assert restored == original, name
        elif name.endswith(".txt"):
            assert restored == original, name
        elif name.endswith(".docx"):
            body = lambda b: re.sub(r"<[^>]+>", "", zipfile.ZipFile(io.BytesIO(b)).read(
                "word/document.xml").decode())
            assert body(restored) == body(original), name
        elif name.endswith(".eml"):
            def bodies(b):
                return [p.get_payload(decode=True).decode().strip() for p in email.message_from_bytes(b).walk()
                        if p.get_content_type() == "text/plain"]
            assert bodies(restored) == bodies(original), name
            assert "Mária Kováčová" in text_of(restored, name)


def test_consistent_tokens_across_files():
    _, out = _run("reversible")
    txt = out["poznamka.txt"][0].decode()
    docx = text_of(out["zmluva.docx"][0], "zmluva.docx")
    base = re.search(r"pán \[(OSOBA_\d+)\]", txt).group(1)
    # varianty [OSOBA_002/2] sú iné gramatické tvary tej istej osoby
    assert re.search(r"Predávajúci: \[" + base + r"(/\d+)?\]", docx), (base, "rovnaká osoba = rovnaký token")
    assert len(set(re.findall(r"\[(OSOBA_\d+)", docx))) == 5, set(re.findall(r"\[(OSOBA_\d+)", docx))


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    failed = 0
    for n, f in tests:
        try:
            f()
            print(f"OK    {n}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {n}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} testov prešlo")
    sys.exit(1 if failed else 0)
