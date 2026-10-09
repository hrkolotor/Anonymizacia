"""End-to-end test rozhrania v reálnom prehliadači (Playwright + Chromium).

Spustenie:  python tests/test_ui.py [priečinok_na_snímky]
"""

from __future__ import annotations

import io
import re
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import make_samples as M  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from anonymizer_sk.webapp.server import App  # noqa: E402
from test_anonymizer import leaked, text_of  # noqa: E402

PW = "testovacie-heslo-123"


def main(shots: Path):
    shots.mkdir(parents=True, exist_ok=True)
    samples = Path(tempfile.mkdtemp(prefix="ui_samples_"))
    M.main(samples)
    files = [str(samples / n) for n in ("zmluva.docx", "email.eml", "poznamka.txt", "zmluva_sken.pdf")]

    app = App(idle_exit=False)
    threading.Thread(target=app.serve, daemon=True).start()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1100, "height": 900}, accept_downloads=True)
        page.goto(app.url)
        page.screenshot(path=str(shots / "1_start.png"))

        page.set_input_files("#pick-anon", files)
        page.wait_for_selector("#files-anon li >> nth=3")
        page.click("#scan")
        page.wait_for_selector("#review:not([hidden])", timeout=180_000)
        lead = page.text_content("#review-lead")
        print("Kontrola:", lead)
        page.screenshot(path=str(shots / "2_kontrola.png"), full_page=True)

        # ponechať organizáciu/IČO firmy: zrušiť zaškrtnutie pri IČO
        ico_row = page.locator(".row").filter(has=page.locator(".value", has_text=re.compile(f"^{M.ICO1}$")))
        ico_row.locator("input[type=checkbox]").uncheck()
        assert "kept" in ico_row.get_attribute("class")
        # doplniť vlastný výraz
        page.click(".add summary")
        page.fill("#add-text", "Mlynské nivy")
        page.click("#add-form button")

        page.check('input[name=mode][value=reversible]')
        page.fill("#pw1", PW)
        page.fill("#pw2", PW)
        page.click("#process")
        page.wait_for_selector("#step-done:not([hidden])", timeout=300_000)
        print("Hotovo:", page.text_content("#done-lead"))
        page.screenshot(path=str(shots / "3_hotovo.png"), full_page=True)

        with page.expect_download() as d:
            page.click("#dl-result")
        result = Path(d.value.path()).read_bytes()
        with page.expect_download() as d:
            page.click("#dl-vault")
        vault = Path(d.value.path()).read_bytes()

        z = zipfile.ZipFile(io.BytesIO(result))
        names = z.namelist()
        print("ZIP:", names)
        assert "protokol.txt" in names
        for n in names:
            if n == "protokol.txt":
                continue
            txt = text_of(z.read(n), n)
            hits = [h for h in leaked(txt) if h not in ()]
            assert not hits, (n, hits)
        docx_text = text_of(z.read("zmluva_anonym.docx"), "zmluva_anonym.docx")
        assert M.ICO1 in docx_text.replace(" ", ""), "IČO malo zostať (používateľ ho ponechal)"
        assert "Mlynské nivy" not in docx_text, "doplnený výraz mal byť skrytý"

        # ---- obnova
        out_dir = Path(tempfile.mkdtemp())
        restore_files = []
        for n in names:
            if n != "protokol.txt":
                (out_dir / n).write_bytes(z.read(n))
                restore_files.append(str(out_dir / n))
        (out_dir / "trezor.vault").write_bytes(vault)
        page.click("#tab-restore")
        page.set_input_files("#pick-restore", restore_files + [str(out_dir / "trezor.vault")])
        page.wait_for_selector("#vault-state.ok")
        page.fill("#pw-restore", "zle-heslo-0000")
        page.click("#restore")
        page.wait_for_selector("#err-restore:not([hidden])", timeout=60_000)
        print("Zlé heslo:", page.text_content("#err-restore"))
        page.fill("#pw-restore", PW)
        page.click("#restore")
        page.wait_for_selector("#restore-done:not([hidden])", timeout=120_000)
        page.screenshot(path=str(shots / "4_obnova.png"), full_page=True)
        with page.expect_download() as d:
            page.click("#dl-restore")
        rz = zipfile.ZipFile(io.BytesIO(Path(d.value.path()).read_bytes()))
        print("Obnovené:", rz.namelist())
        assert rz.read("poznamka_obnovene.txt") == (samples / "poznamka.txt").read_bytes()
        assert rz.read("zmluva_sken_obnovene.pdf") == (samples / "zmluva_sken.pdf").read_bytes()

        page.set_viewport_size({"width": 390, "height": 844})
        page.click("#tab-anon")
        page.screenshot(path=str(shots / "5_mobil.png"), full_page=True)
        browser.close()
    app.stop()
    print("UI test OK")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="ui_shots_")))
