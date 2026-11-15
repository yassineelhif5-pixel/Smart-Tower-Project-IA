"""Générateur PDF sans dépendance (bibliothèque standard), interface identique à `docx` : p(), table(), build().

Utilisé pour les CRA : titres, paragraphes (retour à la ligne automatique), tableaux avec en-tête répété à chaque page,
pied de page numéroté. Polices PDF standard Helvetica / Helvetica-Bold en WinAnsiEncoding (accents et € pris en charge).
"""
import zlib

AVAILABLE = True
MIME = "application/pdf"

_W = {32: 278, 33: 278, 34: 355, 35: 556, 36: 556, 37: 889, 38: 667, 39: 191, 40: 333, 41: 333, 42: 389, 43: 584, 44: 278, 45: 333, 46: 278,
      47: 278, 58: 278, 59: 278, 60: 584, 61: 584, 62: 584, 63: 556, 64: 1015, 65: 667, 66: 667, 67: 722, 68: 722, 69: 667, 70: 611, 71: 778,
      72: 722, 73: 278, 74: 500, 75: 667, 76: 556, 77: 833, 78: 722, 79: 778, 80: 667, 81: 778, 82: 722, 83: 667, 84: 611, 85: 722, 86: 667,
      87: 944, 88: 667, 89: 667, 90: 611, 91: 278, 92: 278, 93: 278, 94: 469, 95: 556, 96: 333, 97: 556, 98: 556, 99: 500, 100: 556, 101: 556,
      102: 278, 103: 556, 104: 556, 105: 222, 106: 222, 107: 500, 108: 222, 109: 833, 110: 556, 111: 556, 112: 556, 113: 556, 114: 333, 115: 500,
      116: 278, 117: 556, 118: 500, 119: 722, 120: 500, 121: 500, 122: 500, 123: 334, 124: 260, 125: 334, 126: 584}
_W.update({c: 556 for c in range(48, 58)})
_BASE = str.maketrans("àâäáãåçéèêëíìîïñóòôöõúùûüýÿÀÂÄÁÃÅÇÉÈÊËÍÌÎÏÑÓÒÔÖÕÚÙÛÜÝœŒæÆ", "aaaaaaceeeeiiiinooooouuuuyyAAAAAACEEEEIIIINOOOOOUUUUYoOaA")


def _width(text, size, bold=False):
    w = sum(_W.get(ord(c), _W.get(ord(c.translate(_BASE)), 556)) for c in text)
    return w * size / 1000 * (1.06 if bold else 1)


def _clean(text):
    t = str(text).replace(" ", " ").replace("\xa0", " ").replace("’", "'").replace("—", "-").replace("–", "-").replace("…", "...")
    return t.encode("cp1252", "replace").decode("cp1252")


def _wrap(text, size, width, bold=False):
    out = []
    for para in _clean(text).split("\n"):
        line = ""
        for word in para.split(" "):
            cand = f"{line} {word}" if line else word
            if _width(cand, size, bold) <= width or not line:
                while _width(cand, size, bold) > width and len(cand) > 1 and not line:  # mot plus long que la colonne
                    cut = len(cand)
                    while cut > 1 and _width(cand[:cut], size, bold) > width:
                        cut -= 1
                    out.append(cand[:cut])
                    cand = cand[cut:]
                line = cand
            else:
                out.append(line)
                line = word
        out.append(line)
    return out or [""]


def _hex(c):
    c = (c or "0F172A").lstrip("#")
    return " ".join(f"{int(c[i:i + 2], 16) / 255:.3f}" for i in (0, 2, 4))


def _esc(s):
    return s.encode("cp1252", "replace").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def p(text, style=None, bold=False, align=None, size=None, color=None):
    return ("p", str(text), style, bold, size, color, align)


def table(rows, widths, header=True, total=False, small=False):
    return ("t", [[str(c) for c in r] for r in rows], widths, header, total, small)


class _Doc:
    def __init__(self, landscape):
        self.W, self.H = (841.89, 595.28) if landscape else (595.28, 841.89)
        self.m = 51.0
        self.pages = []
        self.new_page()

    def new_page(self):
        self.ops = []
        self.pages.append(self.ops)
        self.y = self.H - 46

    def ensure(self, h):
        if self.y - h < 56:
            self.new_page()
            return True
        return False

    def text(self, x, y, s, size, bold=False, color=None):
        self.ops.append(f"BT /{'F2' if bold else 'F1'} {size:.2f} Tf {_hex(color)} rg {x:.2f} {y:.2f} Td (".encode() + _esc(s) + b") Tj ET")

    def rect(self, x, y, w, h, fill=None, stroke="CBD5E1"):
        if fill:
            self.ops.append(f"{_hex(fill)} rg {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f".encode())
        if stroke:
            self.ops.append(f"0.4 w {_hex(stroke)} RG {x:.2f} {y:.2f} {w:.2f} {h:.2f} re S".encode())


def _paragraph(d, text, style, bold, size, color, align):
    if not text.strip():
        d.y -= 6
        return
    if style == "Title":
        sz, bold, color, before, after = 17, True, color or "1E293B", 0, 8
    elif style == "Heading1":
        sz, bold, color, before, after = 12, True, color or "3730A3", 10, 4
    else:
        sz, before, after = (size / 2 if size else 9.5), 0, 3
    lead = sz * 1.3
    width = d.W - 2 * d.m
    d.y -= before
    for line in _wrap(text, sz, width, bold):
        if d.ensure(lead):
            pass
        d.y -= lead
        x = d.m
        if align == "center":
            x = (d.W - _width(line, sz, bold)) / 2
        elif align == "right":
            x = d.W - d.m - _width(line, sz, bold)
        d.text(x, d.y + lead * 0.25, line, sz, bold, color)
    d.y -= after


def _table(d, rows, widths, header, total, small):
    sz = 7.5 if small else 8.5
    lead, pad = sz * 1.25, 2.6
    avail = d.W - 2 * d.m
    cols = [w / 20 for w in widths]
    if sum(cols) > avail:
        k = avail / sum(cols)
        cols = [c * k for c in cols]

    def draw(row, bold, fill):
        lines = [_wrap(c, sz, cols[j] - 2 * pad, bold) for j, c in enumerate(row)]
        h = max(len(x) for x in lines) * lead + 2 * pad
        return lines, h

    def emit(row, bold, fill):
        lines, h = draw(row, bold, fill)
        x = d.m
        for j, cell in enumerate(lines):
            d.rect(x, d.y - h, cols[j], h, fill=fill)
            yy = d.y - pad - sz
            for ln in cell:
                d.text(x + pad, yy, ln, sz, bold)
                yy -= lead
            x += cols[j]
        d.y -= h

    head = rows[0] if header and rows else None
    for i, row in enumerate(rows):
        is_head = header and i == 0
        is_total = total and i == len(rows) - 1
        _, h = draw(row, is_head or is_total, None)
        if d.ensure(h) and head is not None and not is_head:
            emit(head, True, "EEF2FF")
        emit(row, is_head or is_total, "EEF2FF" if is_head else ("F1F5F9" if is_total else None))
    d.y -= 6


def build(title, blocks, landscape=False):
    d = _Doc(landscape)
    for b in blocks:
        if isinstance(b, tuple) and b and b[0] == "p":
            _paragraph(d, *b[1:])
        elif isinstance(b, tuple) and b and b[0] == "t":
            _table(d, *b[1:])
    n = len(d.pages)
    for i, ops in enumerate(d.pages, 1):
        foot = _clean(f"{title} - Project Control Tower - (c) ZirconAI (zirconai.fr)")
        ops.append(f"BT /F1 7.5 Tf {_hex('64748B')} rg {d.m:.2f} 28 Td (".encode() + _esc(foot) + b") Tj ET")
        pg = f"Page {i} / {n}"
        ops.append(f"BT /F1 7.5 Tf {_hex('64748B')} rg {d.W - d.m - _width(pg, 7.5):.2f} 28 Td ({pg}) Tj ET".encode())
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
    kids = []
    for ops in d.pages:
        data = zlib.compress(b"\n".join(ops))
        objs.append(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream")
        content_id = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {d.W:.2f} {d.H:.2f}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                    f"/Contents {content_id} 0 R >>".encode())
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    info = b"<< /Title (" + _esc(_clean(title)) + b") /Author (ZirconAI - Project Control Tower) /Producer (Project Control Tower) >>"
    objs.append(info)
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info {len(objs)} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
