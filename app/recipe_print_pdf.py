"""In-memory, authenticated recipe exports for mobile system share/print menus."""
from io import BytesIO
from pathlib import Path
import zlib
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle


pdfmetrics.registerFont(TTFont('ChenRecipeSans', BytesIO(zlib.decompress((Path(__file__).parent / 'fonts' / 'ChenRecipeSans.ttf.z').read_bytes())))) 


def recipe_pdf(name, layout):
    """Use the same ten-column payload as the HTML print page, without a browser."""
    stream = BytesIO()
    style = ParagraphStyle('recipe', fontName='ChenRecipeSans', fontSize=8.64,
                           leading=11.1, wordWrap='CJK', alignment=TA_CENTER)
    left = ParagraphStyle('method', parent=style, alignment=TA_LEFT)

    def text(value, method=False):
        return Paragraph(escape(str(value or '')).replace('\n', '<br/>'), left if method else style)

    rows = [[text(layout['main_label'])] + [text(v) for v in layout['main_slots']]]
    heights = [8.89 * mm]
    spans = []
    for group in layout['ingredient_groups']:
        row = len(rows)
        rows.append([text(group['name'])] + [text(v['name']) for v in group['items']])
        rows.append([''] + [text(v['amount']) for v in group['items']])
        spans.append(('SPAN', (0, row), (0, row + 1)))
        heights.extend([8.89 * mm, 8.89 * mm])
    header = len(rows)
    rows.append([text('步骤'), text('方法')] + [''] * 8)
    spans.append(('SPAN', (1, header), (9, header)))
    heights.append(11.68 * mm)
    for step in layout['print_steps']:
        method = step['method']
        if step['principle']:
            method += ('\n' if method else '') + '原理：' + step['principle']
        row = len(rows)
        rows.append([text(step['title'], True), text(method, True)] + [''] * 8)
        spans.append(('SPAN', (1, row), (9, row)))
        heights.append(37.59 * mm)

    # Expand dense rows rather than silently cropping content. Extra pages are
    # preferable to losing a user's recipe; ordinary template recipes stay A4.
    for ri, row in enumerate(rows):
        for ci, cell in enumerate(row):
            if isinstance(cell, Paragraph):
                width = (9 if ri >= header and ci == 1 else 1) * 17.19 * mm
                _, height = cell.wrap(width - 1.6 * mm, 100000)
                heights[ri] = max(heights[ri], height + 1.6 * mm)
    table = Table(rows, colWidths=[17.19 * mm] * 10, rowHeights=heights,
                  splitByRow=1, splitInRow=1)
    table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), .75, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), .8 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), .8 * mm),
        ('TOPPADDING', (0, 0), (-1, -1), .8 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), .8 * mm),
    ] + spans))
    doc = SimpleDocTemplate(stream, pagesize=A4, title=str(name),
                            author='晨的小助手', leftMargin=19.05 * mm,
                            rightMargin=19.05 * mm, topMargin=25.4 * mm,
                            bottomMargin=23 * mm)
    doc.build([table])
    return stream.getvalue()
