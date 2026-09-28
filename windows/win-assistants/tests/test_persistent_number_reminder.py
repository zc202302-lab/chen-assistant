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
        marker = 'if inbox_event.kind == "new":'
        self.assertIn(marker, source)
        inbox_branch = source[source.index(marker):]
        self.assertIn("self._show_number_reminder(inbox_event)", inbox_branch)
        self.assertNotIn("self._show_window()", inbox_branch)
        self.assertNotIn('self.tray_icon.notify(detail, "新的待录入号码")', inbox_branch)

    def test_server_pending_ids_remove_web_completed_reminders(self) -> None:
        poll = method_block("_poll", "_reconcile_number_reminder_items")
        self.assertIn("inbox_event.pending_ids is not None", poll)
        self.assertIn("self._reconcile_number_reminder_items(inbox_event.pending_ids)", poll)
        reconcile = method_block("_reconcile_number_reminder_items", "_copy_text")
        self.assertIn("if item_id not in allowed", reconcile)
        self.assertIn("self.number_reminder_items.pop(item_id, None)", reconcile)

    def test_reminder_can_close_until_next_schedule(self) -> None:
        source = method_block("_show_number_reminder", "_open_number_inbox")
        self.assertIn('window.protocol("WM_DELETE_WINDOW", self._hide_number_reminder_until_schedule)', source)
        self.assertIn('window.attributes("-topmost", True)', source)
        self.assertIn("self.number_reminder_items[event.item_id] = event", source)
        hide = method_block("_hide_number_reminder_until_schedule", "_keep_number_reminder_visible")
        self.assertIn("window.withdraw()", hide)
        schedule = method_block("_maybe_show_scheduled_number_reminder", "_render_number_reminder")
        self.assertIn("self.config.number_inbox.reminder_times", schedule)
        self.assertIn("self._number_reminder_last_slot", schedule)

    def test_reminder_has_complete_sync_and_local_dismiss(self) -> None:
        render = method_block("_render_number_reminder", "_show_number_reminder")
        complete = method_block("_complete_number_reminder", "_hide_number_reminder_until_schedule")
        self.assertIn('text="已完成"', render)
        self.assertIn("self.number_inbox_receiver.complete", complete)
        self.assertIn("self._dismiss_number_reminder(item_id)", complete)


if __name__ == "__main__":
    unittest.main()
