from __future__ import annotations

import unittest
from pathlib import Path


APP_SOURCE = (Path(__file__).resolve().parents[1] / "win_assistants" / "app.py").read_text(encoding="utf-8")


def method_block(name: str, next_name: str) -> str:
    start = APP_SOURCE.index(f"    def {name}")
    end = APP_SOURCE.index(f"    def {next_name}", start)
    return APP_SOURCE[start:end]


class TrayUpdaterDispatchTests(unittest.TestCase):
    def test_tray_callbacks_never_call_tk_directly(self) -> None:
        source = method_block("_start_tray", "_show_window")
        self.assertIn('self.ui_actions.put("show")', source)
        self.assertIn('self.ui_actions.put("check_updates")', source)
        self.assertIn('self.ui_actions.put("exit")', source)
        self.assertNotIn("self.root.after", source)

    def test_main_thread_dispatch_executes_update_request(self) -> None:
        source = method_block("_poll_ui_actions", "_set_update_status")
        self.assertIn('action == "check_updates"', source)
        self.assertIn("self._request_update_check()", source)
        self.assertIn("self.root.after(100, self._poll_ui_actions)", source)

    def test_update_flow_has_immediate_visible_status(self) -> None:
        request_source = method_block("_request_update_check", "_finish_update_check")
        self.assertIn("正在检查新版本", request_source)
        self.assertIn("_update_checking", request_source)
        download_source = method_block("_download_and_apply_update", "_toggle_startup")
        self.assertIn("正在安装并重启", download_source)
        self.assertIn("更新失败", download_source)


if __name__ == "__main__":
    unittest.main()
