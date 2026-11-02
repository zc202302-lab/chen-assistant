"""Guard Windows notification behavior against accidental foreground popups."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

APP_PATH = Path(__file__).resolve().parents[1] / "win_assistants" / "app.py"


class SilentNotificationsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def _method(self, name):
        app = next(n for n in self.tree.body if isinstance(n, ast.ClassDef) and n.name == "WinAssistantsApp")
        return next(n for n in app.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)

    def test_new_inbox_items_only_alert_when_shared_policy_allows_instant(self):
        method = self._method("_poll")
        text = ast.unparse(method)
        self.assertIn("self.number_reminder_items[inbox_event.item_id] = inbox_event", text)
        self.assertIn("if policy is not None and allows(policy, 'number_inbox') and policy.get('instant'):", text)
        self.assertIn("self._show_number_reminder(inbox_event)", text)

    def test_sms_code_does_not_raise_window(self):
        method = self._method("_poll")
        text = ast.unparse(method)
        self.assertIn("self._copy_text(event.code)", text)
        self.assertNotIn("self._show_window()", text)
        self.assertNotIn("self.root.bell()", text)

    def test_schedule_uses_shared_policy_and_preserves_old_server_fallback(self):
        source = ast.unparse(self._method("_maybe_show_scheduled_number_reminder"))
        self.assertIn("self.config.reminders", source)
        self.assertIn("if not self.number_reminder_items", source)
        self.assertIn("scheduled_key(policy)", source)
        self.assertIn("allows(policy, 'number_inbox')", source)

    def test_editor_has_no_interval_control(self):
        text = ast.unparse(self._method("_show_number_inbox_settings"))
        self.assertNotIn("检查间隔（秒）", text)
        self.assertIn("电脑提醒规则", text)
        self.assertNotIn("reminder_times_var.get().split()", text)


if __name__ == "__main__":
    unittest.main()
