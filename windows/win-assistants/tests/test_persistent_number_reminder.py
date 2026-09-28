from __future__ import annotations

import unittest
from pathlib import Path


APP_SOURCE = (Path(__file__).resolve().parents[1] / "win_assistants" / "app.py").read_text(encoding="utf-8")


def method_block(name: str, next_name: str) -> str:
    start = APP_SOURCE.index(f"    def {name}(")
    end = APP_SOURCE.index(f"    def {next_name}(", start)
    return APP_SOURCE[start:end]


class PersistentNumberReminderTests(unittest.TestCase):
    def test_new_number_does_not_open_main_window_or_use_transient_tray_notice(self) -> None:
        source = method_block("_poll", "_copy_text")
        self.assertIn('if inbox_event.kind == "new":', source)
        self.assertIn("self._show_number_reminder(inbox_event)", source)
        self.assertNotIn("self._show_window()", source)
        self.assertNotIn('self.tray_icon.notify(detail, "新的待录入号码")', source)

    def test_reminder_is_persistent_and_topmost(self) -> None:
        source = method_block("_show_number_reminder", "_open_number_inbox")
        self.assertIn('window.protocol("WM_DELETE_WINDOW", self._keep_number_reminder_visible)', source)
        self.assertIn('window.attributes("-topmost", True)', source)
        self.assertIn("self.number_reminder_items[event.item_id] = event", source)

    def test_reminder_has_explicit_per_item_close_only(self) -> None:
        render = method_block("_render_number_reminder", "_show_number_reminder")
        dismiss = method_block("_dismiss_number_reminder", "_keep_number_reminder_visible")
        self.assertIn("关闭这条提醒", render)
        self.assertIn("关闭提醒不会修改网页中的待处理状态", render)
        self.assertIn("self.number_reminder_items.pop(item_id, None)", dismiss)
        self.assertIn("self.number_reminder_window.destroy()", dismiss)


if __name__ == "__main__":
    unittest.main()
