import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from win_assistants.work_todos import api_url, NoRedirect
from win_assistants.foxmail import prepare_payment_attachment
from win_assistants.config import WorkTodosConfig


class WorkTodosTests(unittest.TestCase):
    def test_urls_reject_credential_leaks(self):
        self.assertEqual(api_url('https://example.com/'),'https://example.com/api/work-todos')
        for value in ('http://example.com','https://user:pass@example.com','https://example.com/a','https://example.com?x=y','file:///x'):
            with self.assertRaises(ValueError):
                api_url(value)
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None,None,302,'',{},'https://attacker.example')

    def test_config_upgrade(self):
        self.assertEqual(WorkTodosConfig.from_dict(None).protected_token,'')

    def test_fixed_txt_cleanup_and_invalid_payload_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'old.txt').write_text('old')
            (root/'keep.xlsx').write_text('keep')
            (root/'folder.txt').mkdir()
            content = b'new payment'
            digest = hashlib.sha256(content).hexdigest()
            with patch('win_assistants.foxmail.payment_attachment_directory',return_value=root):
                with self.assertRaises(ValueError):
                    prepare_payment_attachment('new.txt',content,'bad')
                self.assertTrue((root/'old.txt').exists())
                result = prepare_payment_attachment('new.txt',content,digest)
                self.assertEqual(result,root/'new.txt')
                self.assertFalse((root/'old.txt').exists())
                self.assertEqual(result.read_bytes(),content)
                self.assertTrue((root/'keep.xlsx').exists())
                self.assertTrue((root/'folder.txt').is_dir())
                other = prepare_payment_attachment('other.txt',content,digest)
                self.assertFalse(result.exists())
                self.assertTrue(other.exists())
