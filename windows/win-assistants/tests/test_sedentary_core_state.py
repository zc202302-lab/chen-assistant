import unittest

from sedentary.state import Phase, SedentaryTracker


class TrackerTests(unittest.TestCase):
    @staticmethod
    def advance(tracker, present, seconds):
        result = None
        whole = int(seconds)
        for _ in range(whole):
            result = tracker.tick(present, 1)
        fraction = seconds - whole
        if fraction:
            result = tracker.tick(present, fraction)
        return result

    def test_reminds_at_limit_only_once(self):
        tracker = SedentaryTracker(10, 3)
        self.assertFalse(tracker.tick(True, 6).reminder_due)
        result = tracker.tick(True, 4)
        self.assertTrue(result.reminder_due)
        self.assertEqual(result.phase, Phase.REMINDING)
        self.assertFalse(tracker.tick(True, 1).reminder_due)

    def test_short_absence_preserves_both_counters(self):
        tracker = SedentaryTracker(10, 3)
        tracker.tick(True, 6)
        tracker.tick(False, 2)
        self.assertEqual(tracker.work_seconds, 6)
        self.assertEqual(tracker.away_seconds, 2)
        tracker.tick(True, 1)
        self.assertEqual(tracker.away_seconds, 2)
        self.assertEqual(tracker.work_seconds, 7)

    def test_long_absence_completes_break_and_resets_cycle(self):
        tracker = SedentaryTracker(10, 3)
        tracker.tick(True, 8)
        result = tracker.tick(False, 3)
        self.assertTrue(result.break_completed)
        self.assertEqual(result.work_seconds, 0)
        self.assertEqual(result.away_seconds, 0)

    def test_full_break_before_limit_starts_new_cycle(self):
        tracker = SedentaryTracker(30 * 60, 10 * 60)
        self.advance(tracker, True, 25 * 60)
        result = self.advance(tracker, False, 10 * 60)
        self.assertTrue(result.break_completed)
        self.advance(tracker, True, 5 * 60)
        self.assertEqual(tracker.work_seconds, 5 * 60)
        self.assertFalse(tracker.reminder_active)

    def test_partial_break_reduces_forced_break_requirement(self):
        tracker = SedentaryTracker(30 * 60, 10 * 60)
        self.advance(tracker, True, 29 * 60)
        self.advance(tracker, False, 8 * 60)
        result = self.advance(tracker, True, 60)
        self.assertTrue(result.reminder_due)
        self.assertEqual(result.away_seconds, 8 * 60)
        self.assertEqual(result.remaining_break_seconds, 2 * 60)
        result = self.advance(tracker, False, 2 * 60)
        self.assertTrue(result.break_completed)
        self.assertFalse(tracker.reminder_active)

    def test_return_during_forced_break_does_not_unlock(self):
        tracker = SedentaryTracker(10, 5)
        tracker.tick(True, 10)
        tracker.tick(False, 2)
        tracker.tick(True, 3)
        self.assertEqual(tracker.work_seconds, 13)
        self.assertEqual(tracker.away_seconds, 2)
        self.assertTrue(tracker.reminder_active)

    def test_no_manual_bypass_api_exists(self):
        tracker = SedentaryTracker(10, 3)
        self.assertFalse(hasattr(tracker, "set_paused"))
        self.assertFalse(hasattr(tracker, "complete_break_manually"))
        self.assertFalse(hasattr(tracker, "snooze"))


if __name__ == "__main__":
    unittest.main()
