"""Exercise the released EXE's integrated bridge on native Windows."""
import ctypes
from ctypes import wintypes
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from win_assistants.sms import protect_secret  # noqa: E402
from test_number_batch import signed, annotated_workbook  # noqa: E402
from frozen_update_restart_acceptance import kill_tree  # noqa: E402


def main(executable):
    assert sys.platform == 'win32', 'requires native Windows'
    with tempfile.TemporaryDirectory(prefix='win-number-batch-') as directory:
        root = Path(directory)
        target = root / 'ChenBridge' / '批量添加集团成员.xlsx'
        target.parent.mkdir()
        template, original_parts = annotated_workbook()
        target.write_bytes(template)
        original = target.read_bytes()
        config_dir = root / 'roaming' / 'win-assistants'
        config_dir.mkdir(parents=True)
        config = {'modules': {key: {'enabled': key == 'number_inbox', 'command': [], 'delay_seconds': 0}
                              for key in ('sms', 'sedentary', 'chen_helper', 'number_inbox')},
                  'number_inbox': {'api_url': 'https://example.invalid/api/number-inbox/pending',
                                   'protected_token': protect_secret('secret'), 'batch_target': str(target), 'reminder_times': []}}
        (config_dir / 'config.json').write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
        env = os.environ.copy()
        env.update(APPDATA=str(root / 'roaming'), LOCALAPPDATA=str(root / 'local'))
        process = subprocess.Popen([str(executable.resolve()), '--background'], env=env)
        def request(path, body=None):
            conn = http.client.HTTPConnection('127.0.0.1', 18764, timeout=5)
            conn.request('POST' if body else 'GET', path, json.dumps(body) if body else None,
                         {'Origin': 'https://assistant.ziboxiaozhushou.cn', 'Content-Type': 'application/json'})
            response = conn.getresponse()
            result = response.status, json.loads(response.read())
            conn.close()
            return result
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                try:
                    if request('/health')[1].get('batch_version') == 1:
                        break
                except OSError:
                    pass
                assert process.poll() is None, 'frozen client exited before bridge startup'
                time.sleep(.5)
            else:
                raise AssertionError('frozen bridge did not start')
            # Hold the workbook like Excel does: deny all file sharing.
            kernel = ctypes.windll.kernel32
            kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                          ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
            kernel.CreateFileW.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            handle = kernel.CreateFileW(str(target), 0x80000000, 0, None, 3, 0, None)
            assert handle not in (None, wintypes.HANDLE(-1).value)
            try:
                status, body = request('/number-batch', signed())
                assert status == 400 and '关闭Excel' in body['error'], body
            finally:
                kernel.CloseHandle(handle)
            assert target.read_bytes() == original
            status, body = request('/number-batch', signed(nonce='b' * 32))
            assert status == 200 and body['count'] == 2, body
            assert Path(body['backup']).read_bytes() == original
            with zipfile.ZipFile(target) as package:
                sheet = package.read('xl/worksheets/sheet1.xml')
                assert b'00123456789' in sheet and b'12345678901234567890' in sheet
                assert b'<f>' not in sheet
                for name, data in original_parts.items():
                    if name != 'xl/worksheets/sheet1.xml':
                        assert package.read(name) == data, f'template part changed: {name}'
            after = target.read_bytes()
            assert request('/number-batch', signed(nonce='b' * 32))[0] == 400
            assert target.read_bytes() == after
            print('FROZEN NUMBER BATCH VERIFIED: DPAPI config, integrated loopback, actual Windows lock, backup and replay protection', flush=True)
        finally:
            kill_tree(process.pid)
            process.wait(timeout=15)


if __name__ == '__main__':
    main(Path(sys.argv[1]))
