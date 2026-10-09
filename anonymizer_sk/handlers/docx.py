"""Word (.docx) na úrovni XML.

Spracúva hlavný text, tabuľky, hlavičky, päty, poznámky pod čiarou, komentáre,
textové polia aj sledované zmeny (vymazaný text w:delText). Meno môže byť v Worde
rozdelené do viacerých "runov" s rôznym formátovaním; text odseku sa preto analyzuje
celý a náhrada sa zapíše do prvého dotknutého runu, z ostatných sa text odstráni.
Formátovanie ostáva zachované. Odstráni autorov z metadát, komentárov a revízií.
"""

from __future__ import annotations

import io
import re
import zipfile

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
T, DT, P = f"{{{W}}}t", f"{{{W}}}delText", f"{{{W}}}p"
FIXED = {f"{{{W}}}tab": "\t", f"{{{W}}}br": "\n", f"{{{W}}}cr": "\n", f"{{{W}}}noBreakHyphen": "-"}
TEXT_PARTS = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$")
RELS_PARTS = re.compile(r"^word/_rels/.*\.rels$")
AUTHOR_ATTRS = [f"{{{W}}}author", f"{{{W}}}initials"]
ANON_AUTHOR = "Anonym"


def _paragraph_nodes(p):
    """Textové uzly odseku (bez vnorených odsekov z textových polí)."""
    nodes = []
    for el in p.iter(T, DT, *FIXED):
        anc = el.getparent()
        while anc is not None and anc.tag != P:
            anc = anc.getparent()
        if anc is not p:
            continue
        if el.tag in (T, DT):
            nodes.append([el, el.text or "", True])
        else:
            nodes.append([el, FIXED[el.tag], False])
    return nodes


def _rewrite(nodes, reps):
    if not reps:
        return
    bounds, pos = [], 0
    for n in nodes:
        bounds.append((pos, pos + len(n[1])))
        pos += len(n[1])
    new = [n[1] for n in nodes]
    for r in sorted(reps, key=lambda r: r.start, reverse=True):
        first = True
        for i, (ns, ne) in enumerate(bounds):
            if not nodes[i][2] or ne <= r.start or ns >= r.end:
                continue
            ls, le = max(r.start, ns) - ns, min(r.end, ne) - ns
            new[i] = new[i][:ls] + (r.token if first else "") + new[i][le:]
            first = False
    for (el, old, writable), txt in zip(nodes, new):
        if writable and txt != old:
            el.text = txt
            el.set(XML_SPACE, "preserve")


def process(data: bytes, planner, cfg=None, name: str = "") -> bytes:
    zin = zipfile.ZipFile(io.BytesIO(data))
    trees, paragraphs = {}, []
    for item in zin.namelist():
        if TEXT_PARTS.match(item):
            root = etree.fromstring(zin.read(item))
            trees[item] = root
            for p in root.iter(P):
                paragraphs.append((item, _paragraph_nodes(p)))

    segments = ["".join(n[1] for n in nodes) for _, nodes in paragraphs]
    for (_, nodes), reps in zip(paragraphs, planner.plan(segments, where="odsek")):
        _rewrite(nodes, reps)

    # polia (HYPERLINK "mailto:...") a externé odkazy
    for root in trees.values():
        for el in root.iter(f"{{{W}}}instrText"):
            if el.text:
                el.text = planner.text(el.text, "pole")
        if not planner.restoring:
            for el in root.iter():
                for attr in AUTHOR_ATTRS:
                    if el.get(attr) is not None:
                        el.set(attr, ANON_AUTHOR if attr.endswith("author") else "A")

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            item = info.filename
            if item in trees:
                payload = etree.tostring(trees[item], xml_declaration=True, encoding="UTF-8", standalone=True)
            elif RELS_PARTS.match(item):
                payload = _process_rels(zin.read(item), planner)
            elif item == "docProps/core.xml" and not planner.restoring:
                payload = _clean_core(zin.read(item), planner)
            elif item == "docProps/app.xml" and not planner.restoring:
                payload = _clean_app(zin.read(item))
            else:
                payload = zin.read(item)
                if item.startswith("word/media/") and not planner.restoring:
                    planner.report.warnings.append(
                        f"{name}: obrázok {item} nebol analyzovaný - skontrolujte ho ručne.")
            zout.writestr(info, payload)
    return out.getvalue()


def _process_rels(raw: bytes, planner) -> bytes:
    root = etree.fromstring(raw)
    for rel in root:
        if rel.get("TargetMode") == "External" and rel.get("Target"):
            rel.set("Target", planner.text(rel.get("Target"), "odkaz"))
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _clean_core(raw: bytes, planner) -> bytes:
    root = etree.fromstring(raw)
    for el in root:
        local = etree.QName(el).localname
        if local in ("creator", "lastModifiedBy"):
            el.text = ANON_AUTHOR
        elif local in ("title", "subject", "description", "keywords") and el.text:
            el.text = planner.text(el.text, "metadata")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _clean_app(raw: bytes) -> bytes:
    root = etree.fromstring(raw)
    for el in root:
        if etree.QName(el).localname in ("Company", "Manager"):
            el.text = ""
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
