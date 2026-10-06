import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from member_add_agent import Agent, MemberTask
from task_journal import BatchJournal, batch_lock


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.agent = Agent(self.root)
        self.agent.prepare()
        self.source = self.root / '号码加集团.xlsx'
        self.source.write_bytes(b'synthetic recovery batch')
        self.tasks = [MemberTask(1, '13800138000', 'test-group'),
                      MemberTask(2, '13800138001', 'test-group')]

    def test_restart_keeps_completed_row_and_does_not_repeat_uncertain_row(self):
        with patch('member_add_agent.read_member_tasks_xlsx', return_value=self.tasks), \
                patch('member_add_agent.MemberAdder.add_one', side_effect=[('已添加', 'confirmed'), KeyboardInterrupt()]) as add:
            with self.assertRaises(KeyboardInterrupt):
                self.agent.process(self.source)
            self.assertEqual(add.call_count, 2)
        self.assertEqual(self.source.read_bytes(), b'synthetic recovery batch')
        with patch('member_add_agent.read_member_tasks_xlsx', return_value=self.tasks), \
                patch('member_add_agent.MemberAdder') as adder:
            result = self.agent.process(self.source)
            adder.assert_not_called()
        rows = json.loads(result.read_text('utf-8'))['results']
        self.assertEqual([r['status'] for r in rows], ['已添加', '结果待人工核对'])
        self.assertTrue(self.source.exists())

    def test_journal_write_failure_before_operation_preserves_relay(self):
        with patch('member_add_agent.read_member_tasks_xlsx', return_value=self.tasks), \
                patch('task_journal.atomic_json', side_effect=OSError('disk full')), \
                patch('member_add_agent.MemberAdder') as adder:
            self.assertIsNone(self.agent.process(self.source))
            adder.assert_not_called()
        self.assertEqual(self.source.read_bytes(), b'synthetic recovery batch')

    def test_result_write_failure_recovers_without_resubmitting(self):
        with patch('member_add_agent.read_member_tasks_xlsx', return_value=self.tasks), \
                patch('member_add_agent.MemberAdder.add_one', return_value=('已添加', 'confirmed')) as add, \
                patch('member_add_agent.atomic_json', side_effect=OSError('result unavailable')):
            self.assertIsNone(self.agent.process(self.source))
            self.assertEqual(add.call_count, 2)
        with patch('member_add_agent.read_member_tasks_xlsx', return_value=self.tasks), \
                patch('member_add_agent.MemberAdder') as adder:
            result = self.agent.process(self.source)
            adder.assert_not_called()
        self.assertEqual([r['status'] for r in json.loads(result.read_text('utf-8'))['results']], ['已添加', '已添加'])

    def test_corrupt_journal_never_starts_browser_or_clears_file(self):
        with batch_lock(self.root / 'journals', self.source.read_bytes()) as path:
            path.write_text('{broken')
        with patch('member_add_agent.read_member_tasks_xlsx', return_value=self.tasks), \
                patch('member_add_agent.MemberAdder') as adder:
            with self.assertRaises(ValueError):
                self.agent.process(self.source)
            adder.assert_not_called()
        self.assertEqual(self.source.read_bytes(), b'synthetic recovery batch')

    def test_same_batch_is_exclusive(self):
        with batch_lock(self.root / 'journals', b'batch'):
            with self.assertRaises(OSError):
                with batch_lock(self.root / 'journals', b'batch'):
                    self.fail('concurrent batch acquired')


if __name__ == '__main__':
    unittest.main()
