import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from offline_update import apply_update, pending, recover_update, main
from task_journal import atomic_json

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

    @patch("offline_update._verify_agent")
    def test_update_retains_backup_and_relay(self, verify):
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

    @patch('offline_update._verify_agent', side_effect=RuntimeError('bad executable'))
    def test_health_failure_restores_version_and_support_files(self, verify):
        with tempfile.TemporaryDirectory() as t:
            bridge, install, package = self.prepare(Path(t))
            (install / 'sync_updates.ps1').write_bytes(b'old script')
            with zipfile.ZipFile(package, 'a') as z:
                z.writestr('sync_updates.ps1', b'new script')
            pointer = bridge / 'updates' / 'latest.json'
            pointer.write_text(json.dumps({'version': 'a' * 40, 'sha256': hashlib.sha256(package.read_bytes()).hexdigest()}))
            with self.assertRaises(RuntimeError):
                apply_update(bridge, install)
            self.assertEqual((install / 'CloudMemberAddAgent.exe').read_bytes(), b'old')
            self.assertEqual((install / 'sync_updates.ps1').read_bytes(), b'old script')
            self.assertEqual(json.loads((install / 'version.json').read_text())['version'], 'b' * 40)
            self.assertFalse((install / '.update-rollback.json').exists())

    def test_crash_marker_restores_install_before_version_comparison(self):
        with tempfile.TemporaryDirectory() as t:
            bridge, install, _ = self.prepare(Path(t))
            backup = install / '.update-backup'
            backup.mkdir()
            (backup / 'CloudMemberAddAgent.exe').write_bytes(b'old')
            (install / 'CloudMemberAddAgent.exe').write_bytes(b'partial new')
            atomic_json(install / '.update-rollback.json', {'CloudMemberAddAgent.exe': True})
            recover_update(install)
            self.assertEqual((install / 'CloudMemberAddAgent.exe').read_bytes(), b'old')

    def test_manual_sync_failure_returns_nonzero_without_retry(self):
        with patch('sys.argv', ['updater', '--sync', '--once']), \
                patch('offline_update.sync_once', side_effect=RuntimeError('offline')) as sync:
            self.assertEqual(main(), 1)
            sync.assert_called_once()

    def test_failed_recovery_never_launches_partially_updated_agent(self):
        with tempfile.TemporaryDirectory() as t:
            install = Path(t)
            (install / '.update-rollback.json').write_text('{}')
            with patch('sys.argv', ['updater']), \
                    patch('sys.frozen', True, create=True), \
                    patch('sys.executable', str(install / 'CloudOfflineUpdater.exe')), \
                    patch('offline_update.apply_update', side_effect=OSError('backup unavailable')), \
                    patch('offline_update.subprocess.run') as launch:
                self.assertEqual(main(), 1)
                launch.assert_not_called()

    @patch('offline_update._verify_agent')
    def test_updater_is_staged_instead_of_overwriting_running_executable(self, verify):
        with tempfile.TemporaryDirectory() as t:
            bridge, install, package = self.prepare(Path(t))
            (install / 'CloudOfflineUpdater.exe').write_bytes(b'running updater')
            with zipfile.ZipFile(package, 'a') as z:
                z.writestr('CloudOfflineUpdater.exe', b'next updater')
            (bridge / 'updates' / 'latest.json').write_text(json.dumps({'version': 'a' * 40, 'sha256': hashlib.sha256(package.read_bytes()).hexdigest()}))
            apply_update(bridge, install)
            self.assertEqual((install / 'CloudOfflineUpdater.exe').read_bytes(), b'running updater')
            self.assertEqual((install / 'CloudOfflineUpdater.next.exe').read_bytes(), b'next updater')

if __name__ == '__main__':
    unittest.main()
