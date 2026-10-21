from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from sedentary.unlock import load_password, matches, password_path, save_password


class PasswordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"APPDATA": self.temp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_arbitrary_unicode_and_spaces_round_trip_without_plaintext(self):
        self.assertIsNone(load_password())
        for value in ["1", "晨的 密码!🙂", "  ", "x" * 1000]:
            record = save_password(value, value)
            self.assertTrue(matches(load_password(), value))
            self.assertFalse(matches(record, value + "x"))
            self.assertEqual(set(record), {"iterations", "salt", "digest"})
            if len(value) > 5:
                self.assertNotIn(value.encode(), password_path().read_bytes())

    def test_invalid_change_preserves_old_password_and_salt_changes(self):
        first = save_password("old", "old")
        for pair in [("", ""), ("new", "other")]:
            with self.assertRaises(ValueError):
                save_password(*pair)
        self.assertTrue(matches(load_password(), "old"))
        self.assertNotEqual(first["salt"], save_password("old", "old")["salt"])

    def test_corruption_is_not_treated_as_first_time_setup(self):
        password_path().write_text("{}")
        with self.assertRaises((ValueError, KeyError)):
            load_password()
        self.assertFalse(matches({"unreadable": True}, "anything"))


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "native Tk display required")
class UnlockWindowTests(PasswordTests):
    def setUp(self):
        super().setUp()
        import tkinter as tk
        from sedentary.ui import SedentaryApp
        from sedentary.camera import CameraStatus
        from sedentary.state import SedentaryTracker
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = SedentaryApp.__new__(SedentaryApp)
        self.app.root = self.root
        self.app.reminder_window = None
        self.app.rest_completed = False
        self.app.camera_status = CameraStatus(True, False, "")
        self.app.tracker = SedentaryTracker(10, 3)
        self.app.tracker.tick(True, 10)
        self.app._publish_runtime_status = lambda: None

    def tearDown(self):
        self.root.destroy()
        self.app = None
        import gc
        gc.collect()
        super().tearDown()

    def finish_rest(self):
        self.app.tracker.tick(False, 3)
        self.app.rest_completed = True
        self.app._update_lock_screen()
        self.root.update()

    def test_countdown_never_auto_closes_and_only_correct_password_unlocks(self):
        save_password(" 晨! ", " 晨! ")
        self.app.show_reminder()
        window = self.app.reminder_window
        self.app.unlock_value.set(" 晨! ")
        self.app._try_unlock()
        self.assertTrue(window.winfo_exists(), "password cannot bypass remaining rest")
        self.finish_rest()
        self.app.close_reminder()
        self.app._update_lock_screen()
        self.assertTrue(window.winfo_exists(), "timer and ordinary close must keep lock")
        self.assertTrue(self.app.unlock_panel.winfo_ismapped())
        self.app.unlock_entry.focus_force()
        self.app._enforce_lock_focus()
        self.root.update()
        self.assertEqual(window.focus_get(), self.app.unlock_entry)
        self.app.unlock_value.set("wrong")
        self.app._try_unlock()
        self.assertTrue(window.winfo_exists())
        self.app.unlock_value.set(" 晨! ")
        self.app._try_unlock()
        self.assertIsNone(self.app.reminder_window)
        self.assertFalse(self.app.rest_completed)
        self.assertEqual(self.app.tracker.work_seconds, 0)
        # A second cycle requires authentication again.
        self.app.tracker.tick(True, 10)
        self.app.show_reminder()
        self.assertFalse(self.app.rest_completed)
        self.assertEqual(self.app.unlock_value.get(), "")

    def test_first_upgrade_sets_confirmed_password_after_rest_only(self):
        self.app.show_reminder()
        self.finish_rest()
        self.app.unlock_value.set("新密码")
        self.app.unlock_confirmation.set("wrong")
        self.app._try_unlock()
        self.assertIsNone(load_password())
        self.assertIsNotNone(self.app.reminder_window)
        self.app.unlock_confirmation.set("新密码")
        self.app._try_unlock()
        self.assertTrue(matches(load_password(), "新密码"))
        self.assertIsNone(self.app.reminder_window)


if __name__ == "__main__":
    unittest.main()
