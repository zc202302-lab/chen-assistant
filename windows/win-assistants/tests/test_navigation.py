from __future__ import annotations

import os
import unittest
import tkinter as tk
from tkinter import ttk
from win_assistants.app import WinAssistantsApp
from win_assistants.modules import MODULES


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "GUI acceptance runs with Windows Tk / X display")
class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.app = WinAssistantsApp.__new__(WinAssistantsApp)
        self.app.root = self.root
        self.app.status_vars = {m.key: tk.StringVar(value="运行中") for m in MODULES}
        self.app.enabled_vars = {m.key: tk.BooleanVar(value=True) for m in MODULES}
        self.app.sms_code_var = tk.StringVar(value="123456")
        self.app.startup_var = tk.BooleanVar(value=False)
        self.app.update_status_var = tk.StringVar(value="就绪")
        self.app.update_progress_var = tk.DoubleVar(value=0)
        self.app._configure_window()
        self.app._build_ui()
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def descendants(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self.descendants(child)

    def test_navigation_hides_other_tasks_and_keeps_live_values(self):
        nav = self.app.navigation
        self.assertEqual([nav.tab(t, "text") for t in nav.tabs()],
                         ["短信", "久坐", "缴费连接", "号码提醒", "设置"])
        self.assertEqual(nav.select(), str(self.app.module_pages["sms"]))
        for key, page in self.app.module_pages.items():
            nav.select(page)
            self.root.update()
            self.assertTrue(page.winfo_ismapped())
            self.assertFalse(self.app.settings_page.winfo_ismapped())
            self.assertFalse(any(isinstance(w, ttk.Checkbutton) for w in self.descendants(page)))
            self.assertFalse(any(isinstance(w, ttk.Button) and w.cget("text") in
                                 ("检查更新", "设置", "重新启动", "接管旧工具启动项")
                                 for w in self.descendants(page)))
            self.app.status_vars[key].set("已停用")
            self.root.update()
            self.assertEqual(self.app.status_vars[key].get(), "已停用")
        self.app._show_settings_page()
        self.root.update()
        self.assertTrue(self.app.settings_page.winfo_ismapped())
        self.assertFalse(any(p.winfo_ismapped() for p in self.app.module_pages.values()))
        self.assertEqual(sum(isinstance(w, ttk.Button) and w.cget("text") == "检查更新"
                             for w in self.descendants(self.app.settings_page)), 1)

    def test_minimum_window_fits_settings_and_navigation(self):
        self.root.geometry("740x560")
        self.app.navigation.select(self.app.settings_page)
        self.root.update()
        self.app.settings_canvas.yview_moveto(1.0)
        self.root.update()
        buttons = [w for w in self.descendants(self.app.settings_page)
                   if isinstance(w, ttk.Button) and w.cget("text") == "检查更新"]
        self.assertEqual(len(buttons), 1)
        button = buttons[0]
        self.assertGreaterEqual(button.winfo_rooty(), self.app.settings_canvas.winfo_rooty())
        self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                             self.app.settings_canvas.winfo_rooty() + self.app.settings_canvas.winfo_height())


if __name__ == "__main__":
    unittest.main()
