import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from member_flow import MemberAdder
from member_models import AutomationError, UncertainSubmission
from relay_store import relay_lease, capture_relay, clear_if_unchanged


class RelayLeaseTests(unittest.TestCase):
    def test_busy_relay_is_not_consumed_and_explains_the_wait(self):
        from member_add_agent import Agent
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'relay.xlsx'
            source.write_bytes(b'pending')
            agent = Agent(Path(root))
            with patch('member_add_agent.capture_relay', side_effect=OSError('busy')), \
                    patch('member_add_agent.print') as notice, patch('member_add_agent.MemberAdder') as adder:
                self.assertIsNone(agent.process(source))
                self.assertIsNone(agent.process(source))
                adder.assert_not_called()
                self.assertEqual(notice.call_count, 1)
            self.assertEqual(source.read_bytes(), b'pending')

    def test_clear_keeps_path_and_newer_content(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'relay.xlsx'
            source.write_bytes(b'old')
            old = capture_relay(source)
            source.write_bytes(b'new')
            self.assertFalse(clear_if_unchanged(source, old, b'empty'))
            self.assertEqual(source.read_bytes(), b'new')
            self.assertTrue(clear_if_unchanged(source, b'new', b'empty'))
            self.assertTrue(source.exists())
            self.assertEqual(source.read_bytes(), b'empty')

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics')
    def test_windows_lease_denies_write_and_replacement(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'relay.xlsx'
            other = Path(root) / 'replacement.xlsx'
            source.write_bytes(b'old')
            other.write_bytes(b'new')
            with relay_lease(source) as stream:
                self.assertEqual(stream.read(), b'old')
                with self.assertRaises(OSError):
                    source.write_bytes(b'overwrite')
                with self.assertRaises(OSError):
                    os.replace(other, source)
            os.replace(other, source)
            self.assertEqual(source.read_bytes(), b'new')


class MemberOperationSafetyTests(unittest.TestCase):
    def test_conflicting_or_missing_group_is_rejected(self):
        target = {'webSocketDebuggerUrl': 'test'}
        for values, expected in [([['wanted']], True), ([[], []], False),
                                 ([['wanted'], ['other']], False)]:
            with patch('member_flow.Cdp'), patch('member_flow._contexts', return_value=list(range(len(values)))), \
                    patch('member_flow._evaluate', side_effect=values):
                self.assertEqual(MemberAdder()._group_matches(target, 'wanted'), expected)

    def test_unverified_group_never_clicks_confirm(self):
        adder = MemberAdder()
        adder._action = Mock()
        adder._group_matches = Mock(return_value=False)
        with self.assertRaises(AutomationError):
            adder._submit({}, {}, '13800138000', 'wanted')
        self.assertEqual(adder._action.call_count, 1)  # Select only; no submit click.

    def test_command_loss_at_confirm_is_uncertain(self):
        adder = MemberAdder()
        adder._group_matches = Mock(return_value=True)
        adder._action = Mock(side_effect=[{'ok': True}, RuntimeError('connection lost')])
        with self.assertRaises(UncertainSubmission):
            adder._submit({}, {}, '13800138000', 'wanted')

    def test_generic_success_text_cannot_confirm_member(self):
        adder = MemberAdder()
        adder._group_matches = Mock(return_value=True)
        adder._with_context = Mock(side_effect=[{'success': True}, False])
        with patch('member_flow._find_targets', return_value=({}, [{'id': 'form'}])), \
                patch('member_flow.time.time', side_effect=[0, 0, 13]), patch('member_flow.time.sleep'):
            with self.assertRaises(UncertainSubmission):
                adder._verify_submission({'id': 'form'}, {}, '13800138000', 'wanted')


if __name__ == '__main__':
    unittest.main()
