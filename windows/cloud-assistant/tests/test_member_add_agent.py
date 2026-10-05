from __future__ import annotations

import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from member_add_agent import Agent, AutomationError, MemberTask, empty_relay_workbook, read_member_tasks_xlsx


class BrowserReadinessTests(unittest.TestCase):
    def test_unavailable_browser_leaves_workbook_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            bridge = Path(temp)
            source = bridge / "号码加集团.xlsx"
            source.write_bytes(b"unconsumed workbook")
            with patch("member_add_agent._find_targets", side_effect=RuntimeError("未连接")):
                with self.assertRaisesRegex(RuntimeError, "未连接"):
                    Agent(bridge).run(once=True)
            self.assertEqual(source.read_bytes(), b"unconsumed workbook")
            self.assertFalse((bridge / "processing").exists())

    def test_page_without_search_is_not_ready(self):
        with patch("member_add_agent._find_targets", return_value=({"id": "main"}, [])), patch(
            "member_add_agent.MemberAdder._with_context", return_value={"ok": False}
        ):
            with self.assertRaisesRegex(AutomationError, "重新登录"):
                Agent().check_browser()

    def test_connection_loss_before_claim_leaves_workbook_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            bridge = Path(temp)
            source = bridge / "号码加集团.xlsx"
            source.write_bytes(b"unconsumed workbook")
            with patch.object(Agent, "check_browser", side_effect=[{}, RuntimeError("连接中断")]):
                with self.assertRaisesRegex(RuntimeError, "连接中断"):
                    Agent(bridge).run(once=True)
            self.assertEqual(source.read_bytes(), b"unconsumed workbook")
            self.assertEqual(list((bridge / "processing").iterdir()), [])


class PermanentRelayTests(unittest.TestCase):
    def test_empty_workbook_is_valid_and_has_no_tasks(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "号码加集团.xlsx"
            source.write_bytes(empty_relay_workbook())
            self.assertEqual(read_member_tasks_xlsx(source, allow_empty=True), [])

    def test_source_remains_during_execution_and_is_cleared_afterward(self):
        with tempfile.TemporaryDirectory() as temp:
            agent = Agent(Path(temp)); agent.prepare()
            source = Path(temp) / "号码加集团.xlsx"
            source.write_bytes(b"batch")
            def add(task):
                self.assertEqual(source.read_bytes(), b"batch")
                return "已添加", "成功"
            with patch("member_add_agent.read_member_tasks_xlsx", return_value=[MemberTask(1, "13800138000", "c7210826122")]), patch("member_add_agent.MemberAdder.add_one", side_effect=add):
                result = agent.process(source)
            self.assertTrue(result.exists())
            self.assertTrue(source.exists())
            self.assertEqual(read_member_tasks_xlsx(source, allow_empty=True), [])
            self.assertIsNone(agent.process(source))

    def test_newer_batch_is_not_cleared(self):
        with tempfile.TemporaryDirectory() as temp:
            agent = Agent(Path(temp)); agent.prepare()
            source = Path(temp) / "号码加集团.xlsx"; source.write_bytes(b"batch")
            def add(task):
                source.write_bytes(b"new batch")
                return "已添加", "成功"
            with patch("member_add_agent.read_member_tasks_xlsx", return_value=[MemberTask(1, "13800138000", "c7210826122")]), patch("member_add_agent.MemberAdder.add_one", side_effect=add):
                agent.process(source)
            self.assertEqual(source.read_bytes(), b"new batch")


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
