import ast
import hashlib
import hmac
import http.client
import io
import json
import os
import queue
import tempfile
import time
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

from win_assistants.number_batch import HEADERS, NS, TAG, build_workbook, write_batch
from win_assistants.number_batch_bridge import NumberBatchBridge, verify_request


def workbook(headers=HEADERS):
    cells = ''.join(f'<c r="{col}1" t="inlineStr"><is><t>{value}</t></is></c>' for col, value in zip('ABCDEF', headers))
    data = f'<worksheet xmlns="{NS}" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:x14ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac" mc:Ignorable="x14ac"><dimension ref="A1:H10"/><sheetData><row r="1">{cells}</row><row r="2" ht="22"><c r="A2" s="1"><v>123</v></c><c r="D2" t="inlineStr"><is><t>旧姓名</t></is></c><c r="H2"><f>1+2</f><v>3</v></c></row><row r="10"><c r="F10" t="inlineStr"><is><t>旧部门</t></is></c></row></sheetData><mergeCells count="1"><mergeCell ref="D2:F2"/></mergeCells></worksheet>'
    parts = {'xl/worksheets/sheet1.xml': data,
             'xl/worksheets/sheet2.xml': '<notes>说明不变</notes>',
             'xl/workbook.xml': f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="成员" sheetId="1" r:id="rId1"/></sheets></workbook>',
             'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>',
             '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def annotated_workbook(ref='A1', row='0', object_type='Note'):
    with zipfile.ZipFile(io.BytesIO(workbook())) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts['xl/worksheets/sheet1.xml'] = parts['xl/worksheets/sheet1.xml'].replace(
        b'</worksheet>', b'<legacyDrawing xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="note"/></worksheet>')
    parts['xl/worksheets/_rels/sheet1.xml.rels'] = b'<Relationships><Relationship Id="note" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/vmlDrawing" Target="../drawings/notes.vml"/><Relationship Id="comments" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="../comments1.xml"/></Relationships>'
    parts['xl/comments1.xml'] = f'<comments xmlns="{NS}"><authors><author>template</author></authors><commentList><comment ref="{ref}" authorId="0"><text><t>Required instruction</t></text></comment></commentList></comments>'.encode()
    parts['xl/drawings/notes.vml'] = f'<xml xmlns:v="urn:schemas-microsoft-com:vml" xmlns:x="urn:schemas-microsoft-com:office:excel"><v:shape><x:ClientData ObjectType="{object_type}"><x:Row>{row}</x:Row><x:Column>0</x:Column></x:ClientData></v:shape></xml>'.encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return buffer.getvalue(), parts

def signed(**overrides):
    payload = dict(version=1, nonce='a' * 32, issued_at=int(time.time()), groups=['G1', 'G2'],
                   numbers=['00123456789', '12345678901234567890'], role='MemberSort0102', manual='1')
    payload.update(overrides)
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return dict(payload=payload, signature=hmac.new(b'secret', data, hashlib.sha256).hexdigest())


class NumberBatchTests(unittest.TestCase):
    def test_gui_consumes_batch_results_on_ui_poll_and_keeps_separate_status(self):
        source = Path(__file__).parents[1] / 'win_assistants' / 'app.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'WinAssistantsApp')
        method = next(n for n in app.body if isinstance(n, ast.FunctionDef) and n.name == '_poll_ui_actions')
        dialogs = Mock()
        scope = {'queue': queue, 'messagebox': dialogs}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), scope)
        fake = Mock()
        fake.number_batch_bridge.events = queue.SimpleQueue()
        fake.ui_actions = queue.Queue()
        fake.number_batch_bridge.events.put({'ok': True, 'count': 3, 'path': 'test.xlsx', 'backup': 'backup.xlsx'})
        fake.number_batch_bridge.events.put({'ok': False, 'error': '请关闭Excel'})
        scope['_poll_ui_actions'](fake)
        dialogs.showinfo.assert_called_once()
        dialogs.showerror.assert_called_once_with('批量添加失败', '请关闭Excel', parent=fake.root)
        self.assertIn('已写入 3 个号码', fake.batch_status_var.set.call_args_list[0].args[0])
        self.assertEqual(fake.batch_status_var.set.call_args_list[1].args[0], '批量添加失败：请关闭Excel')
        fake.root.after.assert_called_once_with(100, fake._poll_ui_actions)

    def test_header_instruction_comments_are_preserved_and_data_comments_rejected(self):
        original, parts = annotated_workbook()
        output = build_workbook(original, ['00123456789'], ['G1'], 'role', '1')
        with zipfile.ZipFile(io.BytesIO(output)) as archive:
            for name, data in parts.items():
                if name != 'xl/worksheets/sheet1.xml':
                    self.assertEqual(archive.read(name), data)
        for args in (('A2', '1', 'Note'), ('A1', '0', 'Button'), ('A1', '1', 'Note')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                build_workbook(annotated_workbook(*args)[0], ['12345'], ['G1'], 'role', '1')

    def test_wrong_file_format_returns_actionable_message(self):
        with self.assertRaisesRegex(ValueError, '另存为'):
            build_workbook(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1', ['12345'], ['G1'], 'role', '1')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('[Content_Types].xml', '<Types/>')
        with self.assertRaisesRegex(ValueError, '完整的XLSX'):
            build_workbook(buffer.getvalue(), ['12345'], ['G1'], 'role', '1')

    def test_clears_every_old_cell_preserves_header_style_notes_and_text(self):
        chooser = iter(['G1', 'G2']).__next__
        output = build_workbook(workbook(), ['00123456789', '12345678901234567890'], ['G1', 'G2'], '=role', '1', choose=lambda _: chooser())
        with zipfile.ZipFile(io.BytesIO(output)) as archive:
            data = archive.read('xl/worksheets/sheet1.xml')
            self.assertIn(b'xmlns:x14ac=', data)
            root = ET.fromstring(data)
            cells = {c.get('r'): c for c in root.iter(TAG('c'))}
            text = lambda ref: ''.join(t.text or '' for t in cells[ref].iter(TAG('t')))
            self.assertEqual(text('A1'), HEADERS[0])
            self.assertEqual(text('A2'), 'G1')
            self.assertEqual(text('A3'), 'G2')
            self.assertEqual(text('C2'), '00123456789')
            self.assertEqual(text('C3'), '12345678901234567890')
            self.assertEqual(text('B2'), '=role')
            self.assertEqual(cells['A2'].get('s'), '1')
            self.assertEqual(cells['A3'].get('s'), '1')
            self.assertEqual(len(cells['H2']), 0)
            self.assertEqual(len(cells['F10']), 0)
            self.assertIsNone(root.find(TAG('mergeCells')))
            self.assertEqual(archive.read('xl/worksheets/sheet2.xml'), '<notes>说明不变</notes>'.encode())

    def test_same_group_can_be_selected_for_every_number(self):
        output = build_workbook(workbook(), ['12345', '67890'], ['G1'], 'role', '1')
        self.assertTrue(output)

    def test_success_keeps_exact_original_backup_and_empty_batch_never_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / '成员.xlsx'
            original = workbook()
            target.write_bytes(original)
            with self.assertRaises(ValueError):
                write_batch(target, [], ['G1'], 'role', '1')
            self.assertEqual(target.read_bytes(), original)
            result = write_batch(target, ['12345'], ['G1'], 'role', '1')
            self.assertEqual(result['count'], 1)
            self.assertEqual(Path(result['backup']).read_bytes(), original)

    def test_excel_lock_replace_failure_keeps_original_and_removes_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / '成员.xlsx'
            target.write_bytes(workbook())
            original = target.read_bytes()
            replace = os.replace
            def locked(src, dest):
                if Path(dest) == target:
                    raise PermissionError('locked')
                return replace(src, dest)
            with patch('win_assistants.number_batch.os.replace', side_effect=locked):
                with self.assertRaisesRegex(ValueError, '关闭Excel'):
                    write_batch(target, ['12345'], ['G1'], 'role', '1')
            self.assertEqual(target.read_bytes(), original)
            self.assertFalse(list(Path(directory).glob('*.tmp')))

    def test_wrong_header_and_malformed_workbook_do_not_write(self):
        with self.assertRaises(ValueError):
            build_workbook(workbook(['集团名称', *HEADERS[1:]]), ['12345'], ['G1'], 'role', '1')

    def test_signature_expiry_and_path_injection_rejected(self):
        self.assertEqual(verify_request(signed(), 'secret')['version'], 1)
        for body in (signed(issued_at=0), signed(target='evil.xlsx'), signed(version=2)):
            with self.assertRaises(ValueError):
                verify_request(body, 'secret')
        with self.assertRaises(ValueError):
            verify_request(signed(), 'different')

    def test_bridge_durable_replay_prevention_and_no_done_side_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / '成员.xlsx'
            target.write_bytes(workbook())
            ledger = Path(directory) / 'requests.json'
            bridge = NumberBatchBridge(lambda: 'secret', lambda: target, ledger=ledger, port=0)
            self.assertEqual(bridge.execute(signed())['count'], 2)
            current = target.read_bytes()
            restarted = NumberBatchBridge(lambda: 'secret', lambda: target, ledger=ledger, port=0)
            with self.assertRaisesRegex(ValueError, '已执行过'):
                restarted.execute(signed())
            self.assertEqual(target.read_bytes(), current)
            restarted.busy.acquire()
            try:
                with self.assertRaisesRegex(ValueError, '另一批'):
                    restarted.execute(signed(nonce='b' * 32))
            finally:
                restarted.busy.release()

    def test_loopback_cors_health_signed_post_and_untrusted_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / '成员.xlsx'
            target.write_bytes(workbook())
            bridge = NumberBatchBridge(lambda: 'secret', lambda: target, ledger=Path(directory) / 'requests.json', port=0)
            self.assertTrue(bridge.start()[0])
            port = bridge.server.server_port
            def request(method, path, body=None, origin='https://assistant.ziboxiaozhushou.cn'):
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
                headers = {'Origin': origin, 'Content-Type': 'application/json'}
                connection.request(method, path, body, headers)
                response = connection.getresponse()
                result = response.status, dict(response.getheaders()), json.loads(response.read())
                connection.close()
                return result
            try:
                self.assertEqual(request('GET', '/health')[2]['batch_version'], 1)
                self.assertEqual(request('OPTIONS', '/number-batch')[1]['Access-Control-Allow-Private-Network'], 'true')
                self.assertEqual(request('POST', '/number-batch', json.dumps(signed()), origin='https://evil.example')[0], 403)
                self.assertEqual(request('POST', '/number-batch', json.dumps(signed()))[2]['count'], 2)
                self.assertEqual(bridge.events.get_nowait()['count'], 2)
                self.assertEqual(request('POST', '/number-batch', json.dumps(signed()))[0], 400)
                self.assertIn('已执行过', bridge.events.get_nowait()['error'])
            finally:
                bridge.stop()


if __name__ == '__main__':
    unittest.main()
