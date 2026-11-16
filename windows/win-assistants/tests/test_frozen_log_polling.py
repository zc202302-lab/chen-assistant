from pathlib import Path
import unittest
from unittest.mock import patch
from frozen_update_restart_acceptance import read_update_log

class FrozenLogPollingTests(unittest.TestCase):
    def test_busy_log_retries_without_discarding_previous_evidence(self):
        with patch.object(Path,'read_text',side_effect=[PermissionError(),'startup confirmed']):
            path=Path('update.log')
            previous=read_update_log(path,'begin update')
            self.assertEqual(previous,'begin update')
            self.assertEqual(read_update_log(path,previous),'startup confirmed')
        with patch.object(Path,'read_text',side_effect=FileNotFoundError()):
            self.assertEqual(read_update_log(Path('missing')),'')
