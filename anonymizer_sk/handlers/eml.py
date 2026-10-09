"""E-maily (.eml).

Spracúva hlavičky s osobnými údajmi (From, To, Cc, Subject ...), textové aj HTML
telá, odkazy mailto:/tel: a prílohy (DOCX, PDF, TXT rekurzívne tými istými
handlermi so spoločnými tokenmi). Smerovacie hlavičky s IP adresami a servermi
(Received, X-Originating-IP, DKIM ...) odstraňuje. Prílohy, ktoré nevie
spracovať (obrázky, archívy ...), z e-mailu odstráni a zapíše do reportu.
"""

from __future__ import annotations

import email
from email import encoders
from email.header import Header, decode_header, make_header
from email.message import Message

import lxml.html

PERSONAL_HEADERS = ["Subject", "From", "To", "Cc", "Bcc", "Reply-To", "Sender", "Return-Path", "Delivered-To",
                    "X-Original-To", "Disposition-Notification-To", "Thread-Topic"]
DROP_HEADERS = ("received", "x-received", "x-originating-ip", "x-sender-ip", "authentication-results",
                "received-spf", "dkim-signature", "x-google-dkim-signature", "arc-", "x-ms-exchange-",
                "x-microsoft-antispam", "x-forefront-", "x-ms-", "x-gm-", "x-google-smtp-source",
                "x-mailgun-", "x-ses-")
SKIP_TAGS = {"script", "style", "head", "title", "meta"}
INLINE_TAGS = {"a", "b", "i", "u", "em", "strong", "span", "font", "small", "big", "sub", "sup", "mark", "abbr",
               "code", "s", "strike", "label", "q", "cite"}


def _hdr_str(value) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _set_header(msg: Message, key: str, value: str):
    del msg[key]
    try:
        value.encode("ascii")
        msg[key] = value
    except UnicodeEncodeError:
        msg[key] = Header(value, "utf-8")


def _html(text: str, planner) -> str:
    doc = lxml.html.document_fromstring(text) if "<html" in text.lower() else lxml.html.fragment_fromstring(
        text, create_parent="div")
    slots = []
    for el in doc.iter():
        if not isinstance(el.tag, str):
            continue
        if el.tag not in SKIP_TAGS and el.text:
            slots.append((el, "text"))
        if el.tail:
            slots.append((el, "tail"))
    segs = [getattr(el, attr) for el, attr in slots]
    from ..core import apply

    def block_of(el, attr):
        node = el if attr == "text" else el.getparent()
        while node is not None and node.tag in INLINE_TAGS:
            node = node.getparent()
        return node

    keys = [block_of(el, attr) for el, attr in slots]
    joiners = []
    for i in range(len(slots)):
        nxt = slots[i + 1] if i + 1 < len(slots) else None
        same = nxt is not None and keys[i + 1] is keys[i] and not (nxt[1] == "tail" and nxt[0].tag == "br")
        joiners.append("" if same else "\n")

    for (el, attr), seg, reps in zip(slots, segs, planner.plan(segs, where="html", joiners=joiners)):
        if reps:
            setattr(el, attr, apply(seg, reps))
    for el in doc.iter("a"):
        href = el.get("href") or ""
        if href.lower().startswith(("mailto:", "tel:")):
            el.set("href", planner.text(href, "odkaz"))
    html = lxml.html.tostring(doc, encoding="unicode", method="html")
    if doc.tag == "div" and "<html" not in text.lower():
        html = html[len("<div>"):-len("</div>")]
    return html


def _body(part: Message, planner):
    raw = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        text = raw.decode(charset)
    except (LookupError, UnicodeDecodeError):
        text = raw.decode("utf-8", errors="replace")
    if part.get_content_subtype() == "html":
        new = _html(text, planner)
    else:
        from .text import process as text_process

        new = text_process(text.encode("utf-8"), planner).decode("utf-8")
    del part["Content-Transfer-Encoding"]
    part.set_payload(new, charset="utf-8")


def _attachment(part: Message, parent: Message, planner, cfg, name_hint: str):
    from . import handler_for

    filename = _hdr_str(part.get_filename() or "")
    handler = handler_for(filename)
    restoring = planner.restoring
    if restoring and handler is not None and handler.__name__.endswith(".pdf"):
        original = planner.vault.get_original(part.get_payload(decode=True) or b"") if planner.vault else None
        if original is not None:
            del part["Content-Transfer-Encoding"]
            part.set_payload(original)
            encoders.encode_base64(part)
        return
    if handler is None:
        if not restoring:
            parent.get_payload().remove(part)
            planner.report.warnings.append(f"{name_hint}: príloha '{filename or part.get_content_type()}' "
                                           f"nie je podporovaná, z e-mailu bola odstránená.")
        return
    data = part.get_payload(decode=True) or b""
    new = handler.process(data, planner, cfg, name=f"{name_hint}/{filename}")
    if handler.__name__.endswith(".pdf") and planner.vault is not None:
        planner.vault.store_original(new, data)
    new_name = planner.filename(filename)
    del part["Content-Transfer-Encoding"]
    part.set_payload(new)
    encoders.encode_base64(part)
    if new_name != filename:
        for key in ("Content-Disposition", "Content-Type"):
            if part.get(key):
                part.set_param("filename" if key == "Content-Disposition" else "name", new_name, header=key)


def process(data: bytes, planner, cfg=None, name: str = "") -> bytes:
    msg = email.message_from_bytes(data)
    if not planner.restoring:
        for key in list(msg.keys()):
            if key.lower().startswith(DROP_HEADERS):
                del msg[key]
    for key in PERSONAL_HEADERS:
        if msg[key] is not None:
            _set_header(msg, key, planner.text(_hdr_str(msg[key]), f"hlavicka:{key}"))

    def walk(part: Message, parent: Message | None):
        if part.is_multipart():
            for sub in list(part.get_payload()):
                walk(sub, part)
            return
        disp = (part.get("Content-Disposition") or "").lower()
        if part.get_content_maintype() == "text" and "attachment" not in disp:
            _body(part, planner)
        elif parent is not None:
            _attachment(part, parent, planner, cfg, name)
        elif not planner.restoring:
            planner.report.warnings.append(f"{name}: neznáme jednodielne telo {part.get_content_type()}.")

    walk(msg, None)
    return msg.as_bytes()
