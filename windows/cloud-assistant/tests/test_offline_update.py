import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from offline_update import apply_update, pending

class UpdateTests(unittest.TestCase):
    def prepare(self, root):
        install = root / 'install'
        install.mkdir()
        (install / 'CloudMemberAddAgent.exe').write_bytes(b'old')
        (install / 'version.json').write_text(json.dumps({'version': 'b' * 40}))
        bridge = root / 'bridge'
        updates = bridge / 'updates'
        updates.mkdir(parents=True)
        relay = bridge / '号码加集团.xlsx'
        relay.write_bytes(b'keep relay')
        package = updates / ('a' * 40 + '.zip')
        with zipfile.ZipFile(package, 'w') as z:
            z.writestr('CloudMemberAddAgent.exe', b'new')
            z.writestr('version.json', json.dumps({'version': 'a' * 40}))
            z.writestr('../unwanted', 'never extracted')
        (updates / 'latest.json').write_text(json.dumps({'version': 'a' * 40, 'sha256': hashlib.sha256(package.read_bytes()).hexdigest()}))
        return bridge, install, package

    def test_update_retains_backup_and_relay(self):
        with tempfile.TemporaryDirectory() as t:
            bridge, install, _ = self.prepare(Path(t))
            self.assertTrue(pending(bridge, install))
            self.assertTrue(apply_update(bridge, install))
            self.assertEqual((install / 'CloudMemberAddAgent.exe').read_bytes(), b'new')
            self.assertEqual((install / 'CloudMemberAddAgent.previous.exe').read_bytes(), b'old')
            self.assertEqual((bridge / '号码加集团.xlsx').read_bytes(), b'keep relay')
            self.assertFalse((Path(t) / 'unwanted').exists())
            self.assertFalse(pending(bridge, install))
            self.assertFalse(apply_update(bridge, install))

    def test_partial_sync_preserves_install(self):
        with tempfile.TemporaryDirectory() as t:
            bridge, install, package = self.prepare(Path(t))
            package.write_bytes(b'incomplete')
            with self.assertRaises(ValueError):
                apply_update(bridge, install)
            self.assertEqual((install / 'CloudMemberAddAgent.exe').read_bytes(), b'old')

if __name__ == '__main__':
    unittest.main()
