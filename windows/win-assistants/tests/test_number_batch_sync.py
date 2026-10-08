import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from win_assistants.number_batch_sync import ReceiptOutbox, signed_receipt
from win_assistants.number_batch_bridge import NumberBatchBridge
from test_number_batch import signed, workbook


class ReceiptSyncTests(unittest.TestCase):
    def test_restart_retry_persists_success_and_never_rewrites_workbook(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'members.xlsx'; target.write_bytes(workbook())
            ledger = Path(directory) / 'ledger.json'
            bridge = NumberBatchBridge(lambda: 'secret', lambda: target, ledger=ledger,
                server_provider=lambda: 'https://assistant.zbassistant.site/api/number-inbox/pending')
            result = bridge.execute(signed())
            stored = json.loads(bridge.receipts.path.read_text())
            self.assertEqual(stored['a' * 32], result['receipt'])
            actual = target.read_bytes()
            with patch.object(bridge.receipts, 'deliver', side_effect=OSError('offline')):
                bridge.receipts.flush()
            self.assertEqual(json.loads(bridge.receipts.path.read_text()), stored)
            restarted = ReceiptOutbox(bridge.receipts.path, lambda: 'secret', lambda: 'url')
            with patch.object(restarted, 'deliver') as deliver:
                restarted.flush()
                deliver.assert_called_once_with(result['receipt'])
            self.assertEqual(json.loads(bridge.receipts.path.read_text()), {})
            self.assertEqual(target.read_bytes(), actual)

    def test_signed_receipt_only_after_success_and_fails_closed_before_write(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'members.xlsx'; target.write_bytes(workbook())
            bridge = NumberBatchBridge(lambda: 'secret', lambda: target, ledger=Path(directory) / 'ledger.json')
            with patch.object(bridge.receipts, 'prepare', side_effect=OSError('outbox locked')):
                with self.assertRaises(OSError): bridge.execute(signed())
            self.assertEqual(target.read_bytes(), workbook())
            target.write_bytes(b'broken')
            with self.assertRaises((ValueError, zipfile.BadZipFile)): bridge.execute(signed())
            self.assertEqual(json.loads(bridge.receipts.path.read_text()), {})

    def test_post_commit_outbox_failure_still_returns_signed_success(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'members.xlsx'; target.write_bytes(workbook())
            bridge = NumberBatchBridge(lambda: 'secret', lambda: target, ledger=Path(directory) / 'ledger.json')
            with patch.object(bridge.receipts, 'add', side_effect=OSError('disk')):
                result = bridge.execute(signed())
            self.assertTrue(result['ok'])
            self.assertEqual(result['receipt']['receipt']['count'], 2)
            self.assertIn('sync_warning', result)

    def test_callback_is_limited_to_configured_product_api(self):
        with tempfile.TemporaryDirectory() as directory:
            outbox = ReceiptOutbox(Path(directory) / 'outbox.json', lambda: 'secret', lambda: 'https://evil.example/api/number-inbox/pending')
            with patch('urllib.request.urlopen') as open_url, self.assertRaises(ValueError):
                outbox.deliver(signed_receipt(signed(), 2, 'secret'))
            open_url.assert_not_called()
