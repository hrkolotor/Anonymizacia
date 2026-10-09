"""Spúšťač desktopovej verzie: spustí lokálny server a otvorí rozhranie v prehliadači.

- jedna inštancia: druhé spustenie len otvorí okno už bežiacej aplikácie,
- po zatvorení okna (alebo 3 minútach bez aktivity) sa aplikácia sama ukončí,
- log ide do %LOCALAPPDATA%\\anonymizer-sk\\anonymizer.log (bez obsahu dokumentov).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler

from .runtime import configure, data_dir

LOCK = "instance.json"


def _setup_logging():
    handler = RotatingFileHandler(data_dir() / "anonymizer.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if sys.stderr is None:                      # PyInstaller --noconsole
        sys.stderr = open(os.devnull, "w")      # noqa: SIM115
        sys.stdout = sys.stderr


def _running_instance() -> str | None:
    lock = data_dir() / LOCK
    try:
        info = json.loads(lock.read_text(encoding="utf-8"))
        req = urllib.request.Request(f"http://127.0.0.1:{info['port']}/api/ping", data=b"{}", method="POST",
                                     headers={"X-Token": info["token"], "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as r:
            if r.status == 200:
                return f"http://127.0.0.1:{info['port']}/?t={info['token']}"
    except Exception:
        return None
    return None


def main(argv=None) -> int:
    _setup_logging()
    log = logging.getLogger("anonymizer_sk")
    url = _running_instance()
    if url:
        webbrowser.open(url)
        return 0

    from .webapp.server import App

    configure()
    config = os.environ.get("ANONYMIZER_CONFIG")
    if not config:
        candidate = data_dir() / "config.yaml"
        config = str(candidate) if candidate.exists() else None
    app = App(config_path=config)
    lock = data_dir() / LOCK
    lock.write_text(json.dumps({"port": app.port, "token": app.token}), encoding="utf-8")
    try:
        os.chmod(lock, 0o600)
    except OSError:
        pass
    log.info("Spustené, port %s", app.port)
    if "--no-browser" not in (argv or sys.argv[1:]):
        webbrowser.open(app.url)
    try:
        app.serve()
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
        log.info("Ukončené")
    return 0


if __name__ == "__main__":
    sys.exit(main())
