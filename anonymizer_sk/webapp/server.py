"""Lokálny webový server pre rozhranie (len 127.0.0.1, bez externých závislostí).

Ochrana: počúva iba na loopbacku, kontroluje hlavičku Host (proti DNS rebindingu)
a každé volanie API musí niesť náhodný token, ktorý pozná len otvorené okno aplikácie.
"""

from __future__ import annotations

import hmac
import json
import logging
import mimetypes
import secrets
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from ..config import Config
from .jobs import JobError, JobStore

log = logging.getLogger(__name__)
STATIC = Path(__file__).resolve().parent / "static"
IDLE_TIMEOUT = 180          # s bez signálu z prehliadača -> ukončiť
BYE_GRACE = 20              # s po zatvorení okna (pre prípad obnovenia stránky)
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                               "frame-ancestors 'none'",
}


class App:
    def __init__(self, config_path: str | None = None, port: int = 0, idle_exit: bool = True):
        self.config_path = config_path
        self.token = secrets.token_urlsafe(24)
        self.jobs = JobStore()
        self.last_seen = time.time()
        self.bye_at: float | None = None
        self.idle_exit = idle_exit
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def config(self) -> Config:
        cfg = Config.load(self.config_path)
        if cfg.engine == "auto":
            cfg.engine = "rules" if self._no_presidio() else "auto"
        return cfg

    @staticmethod
    def _no_presidio() -> bool:
        try:
            import presidio_analyzer  # noqa: F401
        except ImportError:
            return True
        return False

    # ------------------------------------------------------------------ beh
    def serve(self):
        if self.idle_exit:
            threading.Thread(target=self._watchdog, daemon=True).start()
        log.info("Rozhranie beží na %s", self.url.split("?")[0])
        self.httpd.serve_forever(poll_interval=0.5)

    def stop(self):
        threading.Thread(target=self.httpd.shutdown, daemon=True).start()

    def _watchdog(self):
        while True:
            time.sleep(2)
            now = time.time()
            if self.jobs.busy():
                continue
            if self.bye_at and now - self.bye_at > BYE_GRACE and self.last_seen <= self.bye_at:
                log.info("Okno bolo zatvorené – ukončujem.")
                return self.stop()
            if now - self.last_seen > IDLE_TIMEOUT:
                log.info("Žiadna aktivita – ukončujem.")
                return self.stop()

    # ------------------------------------------------------------------ HTTP
    def _handler(self):
        app = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "anonymizer-sk"
            sys_version = ""

            def log_message(self, fmt, *args):      # žiadne URL s názvami súborov v logu
                log.debug("%s %s", self.command, urlparse(self.path).path)

            # ---------------- pomocné
            def _send(self, status, body: bytes = b"", ctype="application/json; charset=utf-8", headers=None):
                self.send_response(status)
                for k, v in {**SECURITY_HEADERS, **(headers or {})}.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _json(self, obj, status=HTTPStatus.OK):
                self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

            def _err(self, status, msg):
                self._json({"error": msg}, status)

            def _host_ok(self) -> bool:
                host = (self.headers.get("Host") or "").lower()
                return host in (f"127.0.0.1:{app.port}", f"localhost:{app.port}")

            def _token_ok(self, query) -> bool:
                tok = self.headers.get("X-Token") or (query.get("t") or [""])[0]
                return hmac.compare_digest(tok.encode(), app.token.encode())

            def _body(self, limit=210 * 1024 * 1024) -> bytes:
                length = int(self.headers.get("Content-Length") or 0)
                if length > limit:
                    raise JobError("Súbor je príliš veľký.")
                return self.rfile.read(length) if length else b""

            def _json_body(self) -> dict:
                raw = self._body(1024 * 1024)
                return json.loads(raw.decode("utf-8")) if raw else {}

            # ---------------- smerovanie
            def do_GET(self):
                self._dispatch("GET")

            def do_POST(self):
                self._dispatch("POST")

            def do_PUT(self):
                self._dispatch("PUT")

            def do_DELETE(self):
                self._dispatch("DELETE")

            def _dispatch(self, method):
                if not self._host_ok():
                    return self._err(HTTPStatus.FORBIDDEN, "Neplatná adresa.")
                url = urlparse(self.path)
                query = parse_qs(url.query)
                parts = [unquote(p) for p in url.path.strip("/").split("/") if p]
                try:
                    if method == "GET" and (not parts or parts[0] == "static"):
                        return self._static(parts, query)
                    if not parts or parts[0] != "api":
                        return self._err(HTTPStatus.NOT_FOUND, "Nenájdené.")
                    if not self._token_ok(query):
                        return self._err(HTTPStatus.UNAUTHORIZED, "Platnosť relácie vypršala. Spustite aplikáciu znova.")
                    app.last_seen = time.time()
                    return self._api(method, parts[1:], query)
                except JobError as exc:
                    return self._err(HTTPStatus.BAD_REQUEST, str(exc))
                except KeyError:
                    return self._err(HTTPStatus.NOT_FOUND, "Úloha neexistuje (aplikácia bola možno reštartovaná).")
                except Exception as exc:  # noqa: BLE001
                    log.exception("Chyba požiadavky")
                    return self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"Neočakávaná chyba: {exc}")

            def _static(self, parts, query):
                if not parts:
                    if not self._token_ok(query):
                        page = (STATIC / "closed.html").read_bytes()
                        return self._send(HTTPStatus.OK, page, "text/html; charset=utf-8")
                    return self._send(HTTPStatus.OK, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                path = (STATIC / "/".join(parts[1:])).resolve()
                if STATIC not in path.parents or not path.is_file():
                    return self._err(HTTPStatus.NOT_FOUND, "Nenájdené.")
                ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype.endswith("javascript"):
                    ctype += "; charset=utf-8"
                return self._send(HTTPStatus.OK, path.read_bytes(), ctype)

            def _api(self, method, p, query):
                if p == ["ping"]:
                    app.bye_at = None
                    return self._json({"ok": True})
                if p == ["bye"]:
                    app.bye_at = time.time()
                    return self._json({"ok": True})
                if p == ["quit"] and method == "POST":
                    self._json({"ok": True})
                    return app.stop()
                if p == ["jobs"] and method == "POST":
                    job = app.jobs.create(self._json_body().get("kind", "anon"))
                    return self._json(job.status(), HTTPStatus.CREATED)
                if len(p) >= 2 and p[0] == "jobs":
                    job = app.jobs.get(p[1])
                    rest = p[2:]
                    if not rest and method == "GET":
                        return self._json(job.status())
                    if not rest and method == "DELETE":
                        app.jobs.delete(job.id)
                        return self._json({"ok": True})
                    if rest == ["files"] and method == "PUT":
                        name = (query.get("name") or ["subor"])[0]
                        with job.lock:
                            stored = job.add_file(name, self._body())
                        return self._json({"name": stored, "status": job.status()})
                    if rest == ["files"] and method == "DELETE":
                        with job.lock:
                            job.remove_file((query.get("name") or [""])[0])
                        return self._json(job.status())
                    if rest == ["scan"] and method == "POST":
                        job.start_scan(app.config())
                        return self._json(job.status(), HTTPStatus.ACCEPTED)
                    if rest == ["process"] and method == "POST":
                        b = self._json_body()
                        job.start_process(app.config(), b.get("mode"), b.get("passphrase", ""),
                                          b.get("excluded", []), b.get("added", []))
                        return self._json(job.status(), HTTPStatus.ACCEPTED)
                    if rest == ["restore"] and method == "POST":
                        job.start_restore(self._json_body().get("passphrase", ""))
                        return self._json(job.status(), HTTPStatus.ACCEPTED)
                    if rest in (["download", "result"], ["download", "vault"]) and method == "GET":
                        data, name = ((job.result, job.result_name) if rest[1] == "result"
                                      else (job.vault_out, job.vault_name))
                        if not data:
                            return self._err(HTTPStatus.NOT_FOUND, "Výsledok ešte nie je pripravený.")
                        ctype = "application/zip" if name.endswith(".zip") else "application/octet-stream"
                        return self._send(HTTPStatus.OK, data, ctype, {
                            "Content-Disposition": f"attachment; filename=\"{name}\"; filename*=UTF-8''{quote(name)}"})
                return self._err(HTTPStatus.NOT_FOUND, "Neznáma požiadavka.")

        return Handler
