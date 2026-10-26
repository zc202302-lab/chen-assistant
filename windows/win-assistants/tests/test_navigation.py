from __future__ import annotations

import os
import gc
import unittest
from win_assistants.modules import MODULES


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "GUI acceptance runs with Windows Tk / X display")
class NavigationTests(unittest.TestCase):
    def setUp(self):
        global tk, ttk
        import tkinter as tk
        from tkinter import ttk
        from win_assistants.app import WinAssistantsApp
        self.root = tk.Tk()
        self.app = WinAssistantsApp.__new__(WinAssistantsApp)
        self.app.root = self.root
        from win_assistants.work_todos import TodoReceiver
        self.app.todo_receiver = TodoReceiver()
        self.app.tray_icon = None
        self.app.status_vars = {m.key: tk.StringVar(value="运行中") for m in MODULES}
        self.app.enabled_vars = {m.key: tk.BooleanVar(value=True) for m in MODULES}
        self.app.sms_code_var = tk.StringVar(value="123456")
        self.app.startup_var = tk.BooleanVar(value=False)
        self.app.update_status_var = tk.StringVar(value="就绪")
        self.app.batch_status_var = tk.StringVar(value="批量添加：尚未执行")
        self.app.update_progress_var = tk.DoubleVar(value=0)
        self.app._configure_window()
        self.app._build_ui()
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        # Dispose Tk variables on their creating thread, before later HTTP tests
        # allocate enough objects to trigger collection on a worker thread.
        self.app = None
        gc.collect()

    def descendants(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self.descendants(child)

    def test_navigation_hides_other_tasks_and_keeps_live_values(self):
        nav = self.app.navigation
        self.assertEqual([nav.tab(t, "text") for t in nav.tabs()],
                         ["短信", "久坐", "缴费连接", "号码提醒", "待办事项", "设置"])
        self.assertEqual(nav.select(), str(self.app.module_pages["sms"]))
        for key, page in self.app.module_pages.items():
            self.app.nav_buttons[str(page)].invoke()
            self.root.update()
            self.assertEqual(nav.select(), str(page))
            self.assertEqual(self.app.nav_indicators[str(page)].cget("bg"), "#2563EB")
            self.assertTrue(page.winfo_ismapped())
            self.assertFalse(self.app.settings_page.winfo_ismapped())
            panel = self.app.module_settings_panels[key]
            self.assertFalse(panel.winfo_ismapped())
            self.assertEqual(sum(isinstance(w, ttk.Checkbutton) for w in self.descendants(page)), 2 if key == "work_todos" else 1)
            self.app.module_settings_buttons[key].invoke()
            self.root.update()
            self.assertTrue(panel.winfo_ismapped())
            self.assertFalse(any(other.winfo_ismapped() for other_key, other in self.app.module_settings_panels.items() if other_key != key))
            self.app.module_settings_buttons[key].invoke()
            self.root.update()
            self.assertFalse(panel.winfo_ismapped())
            self.assertFalse(any(isinstance(w, ttk.Button) and w.cget("text") in
                                 ("检查更新", "设置", "接管旧工具启动项")
                                 for w in self.descendants(page)))
            self.app.status_vars[key].set("已停用")
            self.root.update()
            self.assertEqual(self.app.status_vars[key].get(), "已停用")
        self.app._show_settings_page()
        self.root.update()
        self.assertTrue(self.app.settings_page.winfo_ismapped())
        self.assertEqual(sum(isinstance(w, ttk.Checkbutton) for w in self.descendants(self.app.settings_page)), 1)
        self.assertFalse(any(isinstance(w, ttk.Button) and w.cget("text") in
                             ("短信连接", "久坐设置", "号码提醒设置", "重新连接", "重新启动")
                             for w in self.descendants(self.app.settings_page)))
        self.assertFalse(any(p.winfo_ismapped() for p in self.app.module_pages.values()))
        self.assertEqual(sum(isinstance(w, ttk.Button) and w.cget("text") == "检查更新"
                             for w in self.descendants(self.app.settings_page)), 1)

    def test_todo_due_popup_and_cross_client_completion(self):
        panel = self.app.todo_panel
        item = {'id': 1, 'title': '独立待办', 'note': '备注', 'remind_at': '2020-01-01T09:00',
                'done': 0, 'revision': 1, 'due': True}
        panel.apply({'items': [item]})
        self.root.update()
        self.assertTrue(panel.popup.winfo_exists())
        self.assertEqual(panel.popup_text.get(), '独立待办')
        panel.tree.selection_set('1')
        from unittest.mock import patch
        with patch.object(panel, 'send') as send:
            panel.complete()
            self.assertEqual(send.call_args.args[1], {'action': 'done', 'revision': 1})
        panel.apply({'items': [dict(item, done=1, revision=2, due=False)]})
        self.root.update()
        self.assertIsNone(panel.popup)
        self.assertEqual(panel.tree.get_children(), ())
        panel.show_done.set(True)
        panel.render()
        self.assertTrue(panel.tree.exists('1'))
        panel.tree.selection_set('1')
        with patch.object(panel, 'send') as send:
            panel.complete()
            self.assertEqual(send.call_args.args[1], {'action': 'reopen', 'revision': 2})
        panel.apply({'items': [dict(item, revision=3, remind_at='2099-01-01T09:00', due=False)]})
        self.assertEqual(panel.notified, set())

    def test_batch_result_remains_visible_when_connection_status_changes(self):
        page = self.app.module_pages["number_inbox"]
        self.app.navigation.select(page)
        self.app.batch_status_var.set("批量添加：已写入 3 个号码")
        self.app.status_vars["number_inbox"].set("已连接 · 3 个待录入")
        self.root.update()
        labels = [w for w in self.descendants(page)
                  if isinstance(w, ttk.Label) and str(w.cget("textvariable")) == str(self.app.batch_status_var)]
        self.assertEqual(len(labels), 1)
        self.assertTrue(labels[0].winfo_ismapped())
        self.assertEqual(self.app.batch_status_var.get(), "批量添加：已写入 3 个号码")

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

    def test_fast_switch_settles_and_keyboard_traversal(self):
        nav = self.app.navigation
        for page in self.app.module_pages.values():
            nav.select(page)
            self.root.update()
        nav.select(self.app.settings_page)
        self.root.update()
        self.assertIsNone(self.app._page_transition_job)
        nav.select(self.app.module_pages["sms"])
        self.root.update()
        self.root.after(150, self.root.quit)
        self.root.mainloop()
        self.assertIsNone(self.app._page_transition_job)
        self.assertEqual(tuple(map(int, self.app.module_pages["sms"].cget("padding"))), (20, 20, 20, 20))
        nav.focus_force()
        nav.event_generate("<Control-Tab>")
        self.root.update()
        self.assertEqual(nav.select(), str(self.app.module_pages["sedentary"]))
        self.assertEqual(self.app.sms_code_var.get(), "123456")
        self.app.nav_buttons[str(self.app.module_pages["sedentary"])].focus_force()
        self.root.update()
        self.app.nav_buttons[str(self.app.module_pages["sedentary"])].event_generate("<Right>")
        self.root.update()
        self.assertEqual(nav.select(), str(self.app.module_pages["chen_helper"]))


if __name__ == "__main__":
    unittest.main()




@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "GUI acceptance runs with Windows Tk / X display")
class SedentaryConfirmationSettingsTests(unittest.TestCase):
    def test_confirmation_field_saves_and_restarts_detector(self):
        import tkinter as tk
        from unittest.mock import Mock, patch
        from sedentary.ui import SedentaryApp
        from sedentary.storage import Settings
        from sedentary.state import SedentaryTracker
        root = tk.Tk()
        app = SedentaryApp.__new__(SedentaryApp)
        try:
            app.root = root
            app.embedded_mode = True
            app.settings = Settings(rtsp_host="camera.local", seat_rois=[[0, 0, 1, 1]])
            app.tracker = SedentaryTracker(45 * 60, 3 * 60)
            app.reminder_window = None
            app._configure_window()
            app._build_ui()
            app._saved_signature = app._settings_signature()
            app._last_tested_signature = None
            app.show_settings()
            root.update()
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            widgets = list(descendants(app.settings_window))
            labels = [w.cget("text") for w in widgets if w.winfo_class() == "TLabel"]
            self.assertIn("有人确认（秒）", labels)
            self.assertIn("无人确认（秒）", labels)
            fields = [w for w in widgets if w.winfo_class() == "TSpinbox" and str(w.cget("textvariable")) == str(app.presence_grace_var)]
            self.assertEqual(len(fields), 1)
            fields[0].set("5")
            app._start_detector = Mock()
            with patch.object(app.settings, "save") as save, patch("sedentary.ui.messagebox.showinfo"), patch("sedentary.ui.messagebox.showerror") as error:
                app.save_settings()
                error.assert_not_called()
                save.assert_called_once()
            self.assertEqual(app.settings.presence_grace_seconds, 5)
            self.assertEqual(app.settings.absence_grace_seconds, 8)
            app._start_detector.assert_called_once()
        finally:
            root.destroy()
            app = None
            gc.collect()
