from __future__ import annotations

import inspect
import unittest

from win_assistants.app import WinAssistantsApp


class TrayUpdaterDispatchTests(unittest.TestCase):
    def test_tray_callbacks_never_call_tk_directly(self) -> None:
        source = inspect.getsource(WinAssistantsApp._start_tray)
        self.assertIn('self.ui_actions.put("show")', source)
        self.assertIn('self.ui_actions.put("check_updates")', source)
        self.assertIn('self.ui_actions.put("exit")', source)
        self.assertNotIn("self.root.after", source)

    def test_main_thread_dispatch_executes_update_request(self) -> None:
        source = inspect.getsource(WinAssistantsApp._poll_ui_actions)
        self.assertIn('action == "check_updates"', source)
        self.assertIn("self._request_update_check()", source)
        self.assertIn("self.root.after(100, self._poll_ui_actions)", source)

    def test_update_flow_has_immediate_visible_status(self) -> None:
        source = inspect.getsource(WinAssistantsApp._request_update_check)
        self.assertIn("正在检查新版本", source)
        self.assertIn("_update_checking", source)
        download_source = inspect.getsource(WinAssistantsApp._download_and_apply_update)
        self.assertIn("正在安装并重启", download_source)
        self.assertIn("更新失败", download_source)


if __name__ == "__main__":
    unittest.main()
