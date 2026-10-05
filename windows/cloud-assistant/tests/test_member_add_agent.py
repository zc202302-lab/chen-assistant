from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from member_add_agent import read_member_tasks_xlsx


class MemberWorkbookTests(unittest.TestCase):
    def make_workbook(self, path: Path, cells: str, strings: str) -> None:
        workbook = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>
        <sheet name="号码加集团" sheetId="1" r:id="rId1"/></sheets></workbook>'''
        rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
        <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'''
        sheet = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{cells}</sheetData></worksheet>'''
        shared = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{strings}</sst>'''
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", rels)
            archive.writestr("xl/worksheets/sheet1.xml", sheet)
            archive.writestr("xl/sharedStrings.xml", shared)

    def test_reads_all_rows_as_text_without_header(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "号码加集团.xlsx"
            strings = "".join(f"<si><t>{value}</t></si>" for value in ["0013800138000", "c7210826122", "13800000002"])
            cells = '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
            cells += '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2" t="s"><v>1</v></c></row>'
            self.make_workbook(path, cells, strings)
            tasks = read_member_tasks_xlsx(path)
            self.assertEqual([(x.row_number, x.service_number, x.group_search) for x in tasks], [
                (1, "0013800138000", "c7210826122"),
                (2, "13800000002", "c7210826122"),
            ])

    def test_rejects_invalid_service_number(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.xlsx"
            strings = "<si><t>13800x</t></si><si><t>c7210826122</t></si>"
            cells = '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
            self.make_workbook(path, cells, strings)
            with self.assertRaisesRegex(ValueError, "第 1 行 A 列"):
                read_member_tasks_xlsx(path)


if __name__ == "__main__":
    unittest.main()
