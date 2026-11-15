"""Aperçu HTML d'un .docx (titres, paragraphes, tableaux) pour la visionneuse de documents. Le texte est échappé ; le
résultat est affiché dans une iframe isolée (sandbox), sans script."""
import io
import re
import zipfile
from html import escape

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _text(el):
    out = []
    for node in el.iter():
        if node.tag == W + "t" and node.text:
            out.append(node.text)
        elif node.tag in (W + "br", W + "tab"):
            out.append(" ")
    return "".join(out)


def _para(p):
    style = p.find(f"{W}pPr/{W}pStyle")
    st = style.get(W + "val") if style is not None else ""
    txt = escape(_text(p))
    bold = p.find(f".//{W}b") is not None
    if st.lower().startswith("title"):
        return f"<h1>{txt}</h1>"
    if st.lower().startswith("heading"):
        return f"<h2>{txt}</h2>"
    if not txt.strip():
        return "<div class='sp'></div>"
    return f"<p>{'<b>' + txt + '</b>' if bold else txt}</p>"


def docx_to_html(content, title=""):
    from xml.etree import ElementTree as ET
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    parts = []
    for el in list(body) if body is not None else []:
        if el.tag == W + "p":
            parts.append(_para(el))
        elif el.tag == W + "tbl":
            rows = []
            for i, tr in enumerate(el.findall(W + "tr")):
                tag = "th" if i == 0 else "td"
                cells = "".join(f"<{tag}>{escape(' '.join(_text(p) for p in tc.findall(W + 'p')))}</{tag}>" for tc in tr.findall(W + "tc"))
                rows.append(f"<tr>{cells}</tr>")
            parts.append(f"<table>{''.join(rows)}</table>")
    css = ("body{font-family:Segoe UI,Arial,sans-serif;font-size:13px;color:#0f172a;margin:24px;line-height:1.45}"
           "h1{font-size:22px;margin:0 0 10px;color:#1e293b}h2{font-size:15px;color:#3730a3;margin:16px 0 6px}"
           "p{margin:3px 0}.sp{height:8px}table{border-collapse:collapse;width:100%;margin:6px 0 10px;font-size:12px}"
           "td,th{border:1px solid #cbd5e1;padding:4px 6px;vertical-align:top;text-align:left}th{background:#eef2ff}"
           "tr:last-child td{background:#f8fafc}")
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{escape(title)}</title><style>{css}</style></head><body>{''.join(parts)}</body></html>"


def preview_response(content, mime, name):
    """Réponse JSON pour la visionneuse : {kind: pdf|html|none, html?}. Le PDF est servi par le lien de téléchargement."""
    from rest_framework.response import Response
    if mime == "application/pdf" or name.lower().endswith(".pdf"):
        return Response({"kind": "pdf"})
    if name.lower().endswith(".docx"):
        try:
            return Response({"kind": "html", "html": docx_to_html(bytes(content), name)})
        except Exception:
            return Response({"kind": "none"})
    if name.lower().endswith(".csv"):
        return Response({"kind": "html", "html": "<pre>" + escape(bytes(content).decode("utf-8", "replace")) + "</pre>"})
    return Response({"kind": "none"})
