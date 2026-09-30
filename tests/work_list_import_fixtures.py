"""Small synthetic workbook bytes for import regression tests."""
import io
import struct
import zipfile
from datetime import datetime
from html import escape

def workbook(bad=False, missing_formula=False):
    """Minimal OOXML test fixture, including a separate summary column."""
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    def text(ref, value):
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
    serial = (datetime(2026, 9, 30) - datetime(1899, 12, 30)).days
    rows = ['<row r="1">' + text('A1', '汇总') + ''.join(text(col + '1', label) for col, label in zip('DEFGH', ['号码', '金额', '日期', '客户', '说明'])) + '</row>']
    for row in [2, 3, 5]:
        number = 123 if row != 5 else 456
        amount = text('E' + str(row), '无效金额') if bad and row == 3 else f'<c r="E{row}"><v>125.50</v></c>'
        formula = f'<c r="H{row}"><f>1+1</f></c>' if missing_formula else text('H' + str(row), '=SUM(1,2)')
        rows.append(f'<row r="{row}">' + text('A' + str(row), '不应导入') + f'<c r="D{row}" s="1"><v>{number}</v></c>' + amount + f'<c r="F{row}" s="2"><v>{serial}</v></c>' + text('G' + str(row), '导入客户') + formula + '</row>')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="封面" sheetId="1" r:id="r1"/><sheet name="欠费明细" sheetId="2" r:id="r2"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Target="/xl/worksheets/sheet2.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', f'<worksheet xmlns="{ns}"><sheetData><row r="1">{text("A1", "标题")}</row></sheetData></worksheet>')
        z.writestr('xl/worksheets/sheet2.xml', f'<worksheet xmlns="{ns}"><sheetData>{"".join(rows)}</sheetData></worksheet>')
        z.writestr('xl/styles.xml', f'<styleSheet xmlns="{ns}"><numFmts><numFmt numFmtId="164" formatCode="000000"/></numFmts><cellXfs><xf numFmtId="0"/><xf numFmtId="164"/><xf numFmtId="14"/></cellXfs></styleSheet>')
    return output.getvalue()


def legacy_xls():
    def record(kind, payload):
        return struct.pack('<HH', kind, len(payload)) + payload
    raw = record(9, struct.pack('<HH', 2, 16))
    for row, values in enumerate([['number', 'amount'], ['00123', '250']]):
        for col, value in enumerate(values):
            encoded = value.encode('ascii')
            raw += record(4, struct.pack('<HH', row, col) + b'\x00\x00\x00' + bytes([len(encoded)]) + encoded)
    return raw + record(10, b'')

