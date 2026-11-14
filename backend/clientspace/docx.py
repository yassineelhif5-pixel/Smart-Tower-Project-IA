"""Petit générateur .docx (bibliothèque standard) : titres, paragraphes et tableaux, pour les CRA et les factures."""
import io
import zipfile
from xml.sax.saxutils import escape

from aicalls.docgen import CT, DOC_RELS, RELS, STYLES, W


def p(text, style=None, bold=False, align=None, size=None, color=None):
    ppr = ""
    if style or align:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + (f'<w:jc w:val="{align}"/>' if align else "") + "</w:pPr>"
    rpr = ""
    if bold or size or color:
        rpr = "<w:rPr>" + ("<w:b/>" if bold else "") + (f'<w:color w:val="{color}"/>' if color else "") + (f'<w:sz w:val="{size}"/>' if size else "") + "</w:rPr>"
    return f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">{escape(str(text))}</w:t></w:r></w:p>'


def table(rows, widths, header=True, total=False, small=False):
    """rows : liste de listes de textes. widths en twips (somme ≈ 9600 pour A4 avec marges de 2 cm)."""
    sz = 16 if small else 19
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    out = [f'<w:tbl><w:tblPr><w:tblW w:w="{sum(widths)}" w:type="dxa"/><w:tblBorders>'
           + "".join(f'<w:{b} w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>' for b in ("top", "left", "bottom", "right", "insideH", "insideV"))
           + '</w:tblBorders><w:tblCellMar><w:left w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr>'
           + f"<w:tblGrid>{grid}</w:tblGrid>"]
    for i, row in enumerate(rows):
        head = header and i == 0
        last = total and i == len(rows) - 1
        cells = []
        for j, (cell, w) in enumerate(zip(row, widths)):
            shade = '<w:shd w:val="clear" w:color="auto" w:fill="EEF2FF"/>' if head else ('<w:shd w:val="clear" w:color="auto" w:fill="F1F5F9"/>' if last else "")
            num = j > 0 and isinstance(cell, (int, float)) or (j > 0 and str(cell).replace(" ", "").replace(",", "").replace(".", "").replace("€", "").replace("-", "").isdigit())
            jc = '<w:jc w:val="right"/>' if num and not head else ""
            b = "<w:b/>" if head or last else ""
            cells.append(f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/>{shade}</w:tcPr><w:p><w:pPr><w:spacing w:after="0"/>{jc}</w:pPr>'
                         f'<w:r><w:rPr>{b}<w:sz w:val="{sz}"/></w:rPr><w:t xml:space="preserve">{escape(str(cell))}</w:t></w:r></w:p></w:tc>')
        out.append(f"<w:tr>{''.join(cells)}</w:tr>")
    out.append("</w:tbl>")
    return "".join(out) + p("")


def build(title, blocks, landscape=False):
    body = "".join(blocks)
    size = '<w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/>' if landscape else '<w:pgSz w:w="11906" w:h="16838"/>'
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W}><w:body>{body}'
                f'<w:sectPr>{size}<w:pgMar w:top="1000" w:right="1000" w:bottom="1000" w:left="1000" w:header="600" w:footer="600" w:gutter="0"/>'
                '</w:sectPr></w:body></w:document>')
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>' + escape(title) + '</dc:title>'
            '<dc:creator>Project Control Tower</dc:creator></cp:coreProperties>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", STYLES)
        z.writestr("docProps/core.xml", core)
    return buf.getvalue()
