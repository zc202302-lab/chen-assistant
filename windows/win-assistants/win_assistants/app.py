from __future__ import annotations

import argparse
from pathlib import Path
import queue
import re
import threading
import tkinter as tk
from datetime import datetime
from urllib.parse import urlparse
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .commands import command_for_path, display_path
from .config import AppConfig
from .foxmail import FoxmailBridge
from .modules import MODULES, ModuleManager, default_module_configs, internal_sedentary_command
from .number_inbox import NumberInboxEvent, NumberInboxReceiver
from .single_instance import SingleInstance
from .sms import SmsReceiver, migrate_legacy_config, protect_secret, unprotect_secret
from .sedentary import read_status as read_sedentary_status, send_command as send_sedentary_command, status_text as sedentary_status_text
from .startup import is_startup_enabled, set_startup, stop_legacy_foxmail_processes, take_over_legacy_startup
from .updater import fetch_manifest, launch_replacement, newer_version_available, stage_update, verify_staged_startup


BG = "#F3F6F5"
CARD = "#FFFFFF"
GREEN = "#176D5C"
TEXT = "#172D29"
MUTED = "#657773"
BORDER = "#DFE8E4"
SOFT = "#EAF3EF"


class WinAssistantsApp:
    def __init__(self, root: tk.Tk, start_hidden: bool = False) -> None:
        self.root = root
        self.config = AppConfig.load(default_module_configs())
        migrate_legacy_config(self.config)
        # v0.5.0 migrates the mature sedentary runtime into this same executable.
        # Ignore any legacy D:\\Tools\\chen-sit-guard path retained in config.
        if "sedentary" in self.config.modules:
            self.config.modules["sedentary"].command = internal_sedentary_command()
        self.manager = ModuleManager(self._set_status)
        self.sms_receiver = SmsReceiver()
        self.foxmail_bridge = FoxmailBridge()
        self.number_inbox_receiver = NumberInboxReceiver()
        self.number_reminder_window: tk.Toplevel | None = None
        self.number_reminder_items: dict[int, NumberInboxEvent] = {}
        self._number_reminder_last_slot = ""
        self.tray_icon = None
        self.ui_actions: queue.Queue[str] = queue.Queue()
        self._update_checking = False
        self.sms_code_var = tk.StringVar(value="尚未收到验证码")
        self.update_status_var = tk.StringVar(value="更新状态：就绪")
        self.update_progress_var = tk.DoubleVar(value=0)
        self.status_vars = {item.key: tk.StringVar(value="等待启动") for item in MODULES}
        self.enabled_vars = {item.key: tk.BooleanVar(value=self.config.modules[item.key].enabled) for item in MODULES}
        self.path_vars = {
            item.key: tk.StringVar(value=display_path(self.config.modules[item.key].command))
            for item in MODULES
        }
        self.startup_var = tk.BooleanVar(value=is_startup_enabled())
        self._configure_window()
        self._build_ui()
        tray_ready = self._start_tray()
        self._start_enabled_modules()
        if start_hidden or self.config.start_minimized:
            self.root.after(50, self.root.withdraw if tray_ready else self.root.iconify)
        self.root.after(100, self._poll_ui_actions)
        self.root.after(1000, self._poll)

    def _configure_window(self) -> None:
        self.root.title("晨的小助手 · Windows")
        self.root.geometry("840x660")
        self.root.minsize(740, 560)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.root.withdraw)

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Footer.TFrame", background=CARD)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 21, "bold"))
        style.configure("Eyebrow.TLabel", background=BG, foreground=GREEN, font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("Microsoft YaHei UI", 10))
        style.configure("Card.TLabel", background=CARD, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("Module.TLabel", background=CARD, foreground=TEXT, font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("Detail.TLabel", background=CARD, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("Footer.TLabel", background=CARD, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("TButton", font=("Microsoft YaHei UI", 9), padding=(12, 7),
                        background=SOFT, foreground=TEXT, borderwidth=0)
        style.map("TButton", background=[("active", "#DCEBE4"), ("disabled", "#F0F2F1")])
        style.configure("Accent.TButton", background=GREEN, foreground="#FFFFFF", padding=(15, 8))
        style.map("Accent.TButton", background=[("active", "#115746"), ("disabled", "#B9CBC4")],
                  foreground=[("disabled", "#FFFFFF")])
        style.configure("Module.TCheckbutton", background=CARD, foreground=TEXT)
        style.map("Module.TCheckbutton", background=[("active", CARD)])
        style.configure("Footer.TCheckbutton", background=CARD, foreground=TEXT)
        style.map("Footer.TCheckbutton", background=[("active", CARD)])

        shell = ttk.Frame(self.root, padding=(24, 20, 24, 18))
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell)
        header.pack(fill="x", pady=(0, 18))
        ttk.Label(header, text="工作台 / WINDOWS", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(header, text="晨的小助手", style="Title.TLabel").pack(anchor="w", pady=(3, 2))
        ttk.Label(header, text="Windows 客户端", style="Sub.TLabel").pack(anchor="w")

        style.configure("Navigation.TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 12))
        style.configure("Navigation.TNotebook.Tab", padding=(18, 10), font=("Microsoft YaHei UI", 10),
                        background=SOFT, foreground=MUTED)
        style.map("Navigation.TNotebook.Tab", background=[("selected", GREEN), ("active", "#DCEBE4")],
                  foreground=[("selected", "#FFFFFF")])
        self.navigation = ttk.Notebook(shell, style="Navigation.TNotebook", takefocus=True)
        self.navigation.pack(fill="both", expand=True)
        self.module_pages = {}
        labels = {"sms": "短信", "sedentary": "久坐", "chen_helper": "缴费连接", "number_inbox": "号码提醒"}
        for item in MODULES:
            page = ttk.Frame(self.navigation, padding=(20, 20), style="Card.TFrame")
            self.module_pages[item.key] = page
            self.navigation.add(page, text=labels[item.key])
            ttk.Label(page, text=item.name, style="Module.TLabel").pack(anchor="w")
            ttk.Label(page, textvariable=self.status_vars[item.key], style="Detail.TLabel",
                      wraplength=620).pack(anchor="w", pady=(8, 24))
            if item.key == "sms":
                tk.Label(page, textvariable=self.sms_code_var, bg=CARD, fg=GREEN,
                         font=("Microsoft YaHei UI", 30, "bold"), wraplength=620).pack(anchor="w", pady=(12, 24))
                ttk.Button(page, text="复制验证码", command=self._copy_sms_code,
                           style="Accent.TButton").pack(anchor="w")
            elif item.key == "sedentary":
                ttk.Button(page, text="打开状态", command=lambda: self._sedentary_command("show_status"),
                           style="Accent.TButton").pack(anchor="w")
            elif item.key == "number_inbox":
                ttk.Button(page, text="查看未加号码", command=self._open_number_inbox,
                           style="Accent.TButton").pack(anchor="w")
            else:
                ttk.Label(page, text="从网页版发起缴费后，在 Foxmail 中粘贴附件并人工发送。",
                          style="Detail.TLabel", wraplength=620).pack(anchor="w")

        self.settings_page = ttk.Frame(self.navigation, style="Card.TFrame")
        self.navigation.add(self.settings_page, text="设置")
        self.settings_canvas = tk.Canvas(self.settings_page, bg=CARD, highlightthickness=0)
        settings_scroll = ttk.Scrollbar(self.settings_page, orient="vertical", command=self.settings_canvas.yview)
        settings_scroll.pack(side="right", fill="y")
        self.settings_canvas.pack(side="left", fill="both", expand=True)
        self.settings_canvas.configure(yscrollcommand=settings_scroll.set)
        self.settings_content = ttk.Frame(self.settings_canvas, padding=(20, 16), style="Card.TFrame")
        settings_window = self.settings_canvas.create_window((0, 0), window=self.settings_content, anchor="nw")
        self.settings_content.bind("<Configure>", lambda _event: self.settings_canvas.configure(
            scrollregion=self.settings_canvas.bbox("all")))
        self.settings_canvas.bind("<Configure>", lambda event: self.settings_canvas.itemconfigure(
            settings_window, width=event.width))
        def settings_wheel(event) -> None:
            self.settings_canvas.yview_scroll(-3 if event.delta > 0 else 3, "units")
        self.settings_canvas.bind("<MouseWheel>", settings_wheel)
        self.settings_content.bind("<MouseWheel>", settings_wheel)
        ttk.Label(self.settings_content, text="模块设置", style="Module.TLabel").pack(anchor="w", pady=(0, 12))
        settings_actions = {
            "sms": ("短信连接", self._show_sms_settings),
            "sedentary": ("久坐设置", lambda: self._sedentary_command("show_settings")),
            "number_inbox": ("号码提醒设置", self._show_number_inbox_settings),
            "chen_helper": ("重新连接", lambda: self._start_one("chen_helper")),
        }
        for item in MODULES:
            row = ttk.Frame(self.settings_content, style="Card.TFrame")
            row.pack(fill="x", pady=(0, 10))
            ttk.Checkbutton(row, text=item.name, variable=self.enabled_vars[item.key],
                            command=lambda key=item.key: self._toggle_module(key),
                            style="Module.TCheckbutton").pack(side="left")
            label, command = settings_actions[item.key]
            ttk.Button(row, text=label, command=command).pack(side="right")
            if item.key == "sedentary":
                ttk.Button(row, text="重新启动", command=self._restart_sedentary).pack(side="right", padx=8)

        ttk.Separator(self.settings_content).pack(fill="x", pady=(6, 16))
        ttk.Label(self.settings_content, text="启动与更新", style="Module.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Checkbutton(self.settings_content, text="登录 Windows 后在托盘启动", variable=self.startup_var,
                        command=self._toggle_startup, style="Footer.TCheckbutton").pack(anchor="w")
        buttons = ttk.Frame(self.settings_content, style="Card.TFrame")
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="接管旧工具启动项", command=self._take_over).pack(side="left")
        ttk.Button(buttons, text="检查更新", command=self._request_update_check,
                   style="Accent.TButton").pack(side="right")
        ttk.Label(self.settings_content, textvariable=self.update_status_var, style="Footer.TLabel",
                  wraplength=620).pack(anchor="w", pady=(12, 0))
        self.update_progress_bar = ttk.Progressbar(
            self.settings_content, mode="determinate", maximum=100, variable=self.update_progress_var)
        ttk.Label(self.settings_content, text=f"版本 v{__version__}", style="Footer.TLabel").pack(anchor="w", pady=(12, 0))
        self.navigation.select(self.module_pages["sms"])

    def _show_settings_page(self) -> None:
        self.navigation.select(self.settings_page)
        self._show_window()

    def _save_ui(self) -> None:
        for item in MODULES:
            cfg = self.config.modules[item.key]
            cfg.enabled = bool(self.enabled_vars[item.key].get())
            if item.key in ("sms", "chen_helper", "number_inbox"):
                cfg.command = []
                continue
            if item.key == "sedentary":
                cfg.command = internal_sedentary_command()
                continue
            path = self.path_vars[item.key].get().strip()
            if path:
                if path != display_path(cfg.command):
                    cfg.command = command_for_path(item.key, path)
            elif cfg.command:
                cfg.command = []
        self.config.save()

    def _choose_path(self, key: str) -> None:
        if key in ("sms", "chen_helper", "sedentary"):
            return
        path = filedialog.askopenfilename(title="选择模块程序", filetypes=[("程序或脚本", "*.exe *.py *.ps1"), ("所有文件", "*.*")])
        if not path:
            return
        cfg = self.config.modules[key]
        cfg.command = command_for_path(key, path)
        self.path_vars[key].set(path)
        self.config.save()

    def _start_enabled_modules(self) -> None:
        for item in MODULES:
            cfg = self.config.modules[item.key]
            if not cfg.enabled:
                self.status_vars[item.key].set("已停用")
                continue
            self.status_vars[item.key].set(f"{cfg.delay_seconds} 秒后启动")
            self.root.after(cfg.delay_seconds * 1000, lambda key=item.key: self._start_one(key))

    def _toggle_module(self, key: str) -> None:
        self._save_ui()
        if self.enabled_vars[key].get():
            self._start_one(key)
        else:
            if key == "sms":
                self.sms_receiver.stop()
            elif key == "chen_helper":
                self.foxmail_bridge.stop()
            elif key == "sedentary":
                self.manager.stop(key)
            elif key == "number_inbox":
                self.number_inbox_receiver.stop()
            self.status_vars[key].set("已停用")

    def _start_one(self, key: str) -> None:
        self._save_ui()
        if key == "sms":
            try:
                token = unprotect_secret(self.config.sms.protected_token)
            except Exception as exc:
                self.status_vars[key].set(f"令牌读取失败：{exc}")
                return
            if not token:
                self.status_vars[key].set("请先完成设置")
                return
            self.sms_receiver.start(self.config.sms, token)
            self.status_vars[key].set("正在连接")
            return
        if key == "chen_helper":
            self.foxmail_bridge.stop()
            ok, detail = self.foxmail_bridge.start()
            self.status_vars[key].set(detail if ok else f"启动失败：{detail}")
            return
        if key == "number_inbox":
            try:
                token = unprotect_secret(self.config.number_inbox.protected_token)
            except Exception as exc:
                self.status_vars[key].set(f"连接码读取失败：{exc}")
                return
            if not token:
                self.status_vars[key].set("请先完成设置")
                return
            self.number_inbox_receiver.start(self.config.number_inbox, token)
            self.status_vars[key].set("正在连接")
            return
        ok, detail = self.manager.start(key, self.config.modules[key])
        self.status_vars[key].set(detail)

    def _restart_sedentary(self, key: str = "sedentary") -> None:
        self.manager.stop(key)
        self.root.after(400, lambda: self._start_one(key))

    def _set_status(self, key: str, status: str) -> None:
        variable = self.status_vars.get(key)
        if variable:
            variable.set(status)

    def _poll_ui_actions(self) -> None:
        while True:
            try:
                action = self.ui_actions.get_nowait()
            except queue.Empty:
                break
            if action == "show":
                self._show_window()
            elif action == "check_updates":
                self._request_update_check()
            elif action == "exit":
                self._exit()
        self.root.after(100, self._poll_ui_actions)

    def _set_update_status(self, text: str, *, notify: bool = False) -> None:
        self.update_status_var.set(text)
        if notify and self.tray_icon is not None:
            try:
                self.tray_icon.notify(text, "win-assistants 更新")
            except Exception:
                pass

    def _poll(self) -> None:
        self.manager.refresh()
        status = read_sedentary_status()
        if status:
            self.status_vars["sedentary"].set(sedentary_status_text(status))
        while True:
            try:
                event = self.sms_receiver.events.get_nowait()
            except queue.Empty:
                break
            self.status_vars["sms"].set(event.message)
            if event.kind == "message":
                if event.code:
                    self.sms_code_var.set(event.code)
                    self.root.bell()
                    self._show_window()
                if event.marker:
                    self.config.sms.marker = event.marker
                    self.config.save()

        while True:
            try:
                inbox_event = self.number_inbox_receiver.events.get_nowait()
            except queue.Empty:
                break
            self.status_vars["number_inbox"].set(inbox_event.message)
            if inbox_event.pending_ids is not None:
                self._reconcile_number_reminder_items(inbox_event.pending_ids)
            if inbox_event.item_id > self.config.number_inbox.last_seen_id:
                self.config.number_inbox.last_seen_id = inbox_event.item_id
                self.config.save()
            if inbox_event.kind == "snapshot":
                self.number_reminder_items[inbox_event.item_id] = inbox_event
            elif inbox_event.kind == "new":
                self._show_number_reminder(inbox_event)
        self._maybe_show_scheduled_number_reminder()
        self.root.after(1500, self._poll)

    def _reconcile_number_reminder_items(self, pending_ids: tuple[int, ...]) -> None:
        allowed = set(pending_ids)
        removed = False
        for item_id in list(self.number_reminder_items):
            if item_id not in allowed:
                self.number_reminder_items.pop(item_id, None)
                removed = True
        if not removed:
            return
        if not self.number_reminder_items:
            if self.number_reminder_window is not None and self.number_reminder_window.winfo_exists():
                self.number_reminder_window.destroy()
            self.number_reminder_window = None
        elif self.number_reminder_window is not None and self.number_reminder_window.winfo_exists():
            self._render_number_reminder()

    def _copy_text(self, value: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)

    def _position_number_reminder(self) -> None:
        window = self.number_reminder_window
        if window is None or not window.winfo_exists():
            return
        window.update_idletasks()
        width = max(420, window.winfo_reqwidth())
        height = min(620, max(220, window.winfo_reqheight()))
        screen_w = window.winfo_screenwidth()
        screen_h = window.winfo_screenheight()
        x = max(0, screen_w - width - 24)
        y = max(0, screen_h - height - 72)
        window.geometry(f"{width}x{height}+{x}+{y}")

    def _dismiss_number_reminder(self, item_id: int) -> None:
        self.number_reminder_items.pop(item_id, None)
        if not self.number_reminder_items:
            if self.number_reminder_window is not None and self.number_reminder_window.winfo_exists():
                self.number_reminder_window.destroy()
            self.number_reminder_window = None
            return
        self._render_number_reminder()

    def _complete_number_reminder(self, item_id: int) -> None:
        if item_id not in self.number_reminder_items:
            return
        try:
            token = unprotect_secret(self.config.number_inbox.protected_token)
        except Exception as exc:
            messagebox.showerror("号码提醒", f"连接码读取失败：{exc}", parent=self.number_reminder_window)
            return
        if not token:
            messagebox.showerror("号码提醒", "请先完成号码提醒设置。", parent=self.number_reminder_window)
            return

        def worker() -> None:
            try:
                self.number_inbox_receiver.complete(self.config.number_inbox, token, item_id)
            except Exception as exc:
                self.root.after(
                    0,
                    lambda: messagebox.showerror("号码提醒", f"同步已完成状态失败：{exc}", parent=self.number_reminder_window),
                )
                return
            self.root.after(0, lambda: self._dismiss_number_reminder(item_id))

        threading.Thread(target=worker, name="number-inbox-complete", daemon=True).start()

    def _hide_number_reminder_until_schedule(self) -> None:
        window = self.number_reminder_window
        if window is None or not window.winfo_exists():
            return
        window.withdraw()

    def _keep_number_reminder_visible(self) -> None:
        window = self.number_reminder_window
        if window is None or not window.winfo_exists():
            return
        window.deiconify()
        window.lift()
        try:
            window.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.root.bell()

    def _maybe_show_scheduled_number_reminder(self) -> None:
        if not self.number_reminder_items:
            return
        now = datetime.now()
        slot = now.strftime("%H:%M")
        if slot not in self.config.number_inbox.reminder_times:
            return
        key = now.strftime("%Y-%m-%d ") + slot
        if key == self._number_reminder_last_slot:
            return
        self._number_reminder_last_slot = key
        if self.number_reminder_window is None or not self.number_reminder_window.winfo_exists():
            window = tk.Toplevel(self.root)
            self.number_reminder_window = window
            window.title("待录入号码提醒")
            window.resizable(True, True)
            window.minsize(420, 220)
            window.configure(bg=CARD)
            window.protocol("WM_DELETE_WINDOW", self._hide_number_reminder_until_schedule)
            try:
                window.attributes("-topmost", True)
            except tk.TclError:
                pass
            self._render_number_reminder()
        self._keep_number_reminder_visible()

    def _render_number_reminder(self) -> None:
        window = self.number_reminder_window
        if window is None or not window.winfo_exists():
            return

        for child in window.winfo_children():
            child.destroy()

        outer = ttk.Frame(window, padding=16)
        outer.pack(fill="both", expand=True)

        head = ttk.Frame(outer)
        head.pack(fill="x")
        ttk.Label(head, text="待录入号码提醒", font=("Microsoft YaHei UI", 15, "bold")).pack(side="left")
        ttk.Label(
            head,
            text=f"{len(self.number_reminder_items)} 条待处理提醒",
            foreground=MUTED,
        ).pack(side="right")
        ttk.Label(
            outer,
            text="可直接完成并同步网页状态；关闭窗口后，会在下一个设定提醒时间重新弹出仍未完成的号码。",
            foreground=MUTED,
            wraplength=390,
        ).pack(anchor="w", pady=(6, 12))

        list_holder = ttk.Frame(outer)
        list_holder.pack(fill="both", expand=True)
        canvas = tk.Canvas(list_holder, highlightthickness=0, borderwidth=0, background=CARD)
        scrollbar = ttk.Scrollbar(list_holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        cards = ttk.Frame(canvas)
        cards_window = canvas.create_window((0, 0), window=cards, anchor="nw")
        cards.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(cards_window, width=event.width))

        for item_id in sorted(self.number_reminder_items, reverse=True):
            item = self.number_reminder_items[item_id]
            card = ttk.Frame(cards, padding=12)
            card.pack(fill="x", pady=(0, 10))

            ttk.Label(
                card,
                text=item.number or "未填写号码",
                font=("Microsoft YaHei UI", 16, "bold"),
            ).pack(anchor="w")

            meta = item.submitter.strip() if item.submitter else "未填写提交人"
            ttk.Label(card, text=f"提交人：{meta}", foreground=MUTED).pack(anchor="w", pady=(4, 0))
            if item.note:
                ttk.Label(card, text=f"备注：{item.note}", wraplength=360).pack(anchor="w", pady=(4, 0))

            actions = ttk.Frame(card)
            actions.pack(fill="x", pady=(10, 0))
            ttk.Button(
                actions,
                text="复制号码",
                command=lambda value=item.number: self._copy_text(value),
            ).pack(side="left")
            ttk.Button(
                actions,
                text="打开待录入",
                command=self._open_number_inbox,
            ).pack(side="left", padx=(8, 0))
            ttk.Button(
                actions,
                text="已完成",
                command=lambda value=item_id: self._complete_number_reminder(value),
            ).pack(side="right")

        ttk.Label(
            outer,
            text="“已完成”会同步网页后台并移除该号码；直接关闭窗口只会暂时隐藏，下一提醒时间仍会弹出未完成号码。",
            foreground=MUTED,
        ).pack(anchor="w", pady=(8, 0))

        self._position_number_reminder()

    def _show_number_reminder(self, event: NumberInboxEvent) -> None:
        if event.item_id <= 0:
            return
        self.number_reminder_items[event.item_id] = event

        if self.number_reminder_window is None or not self.number_reminder_window.winfo_exists():
            window = tk.Toplevel(self.root)
            self.number_reminder_window = window
            window.title("待录入号码提醒")
            window.resizable(True, True)
            window.minsize(420, 220)
            window.configure(bg=CARD)
            window.protocol("WM_DELETE_WINDOW", self._hide_number_reminder_until_schedule)
            try:
                window.attributes("-topmost", True)
            except tk.TclError:
                pass

        self._render_number_reminder()
        self._keep_number_reminder_visible()

    def _open_number_inbox(self) -> None:
        import webbrowser
        webbrowser.open("https://assistant.ziboxiaozhushou.cn/work/number-inbox")

    def _show_number_inbox_settings(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("号码提醒设置")
        window.geometry("650x400")
        window.resizable(False, False)
        frame = ttk.Frame(window, padding=20)
        frame.pack(fill="both", expand=True)

        api_var = tk.StringVar(value=self.config.number_inbox.api_url)
        try:
            current_token = unprotect_secret(self.config.number_inbox.protected_token)
        except Exception:
            current_token = ""
        token_var = tk.StringVar(value=current_token)
        interval_var = tk.IntVar(value=self.config.number_inbox.interval_seconds)
        reminder_times_var = tk.StringVar(value=", ".join(self.config.number_inbox.reminder_times))

        ttk.Label(frame, text="服务器地址").grid(row=0, column=0, sticky="w", pady=7)
        ttk.Entry(frame, textvariable=api_var, width=57).grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=7)
        ttk.Label(frame, text="提醒连接码").grid(row=1, column=0, sticky="w", pady=7)
        ttk.Entry(frame, textvariable=token_var, show="●", width=57).grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=7)
        ttk.Label(frame, text="检查间隔（秒）").grid(row=2, column=0, sticky="w", pady=7)
        ttk.Spinbox(frame, from_=10, to=120, textvariable=interval_var, width=8).grid(row=2, column=1, sticky="w", padx=(12, 0), pady=7)
        ttk.Label(frame, text="定时提醒（最多5个）").grid(row=3, column=0, sticky="w", pady=7)
        ttk.Entry(frame, textvariable=reminder_times_var, width=57).grid(row=3, column=1, sticky="ew", padx=(12, 0), pady=7)
        ttk.Label(
            frame,
            text="格式示例：09:00, 16:00。新号码仍会即时提醒；关闭提醒窗口后，未完成号码会在下一个设定时间再次弹出。",
            style="Sub.TLabel",
            wraplength=570,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 18))
        frame.columnconfigure(1, weight=1)

        def save_and_connect() -> None:
            api_url = api_var.get().strip()
            token = token_var.get().strip()
            parsed = urlparse(api_url)
            if parsed.scheme.lower() != "https" or not parsed.netloc:
                messagebox.showerror("号码提醒", "服务器地址必须是 HTTPS 地址。", parent=window)
                return
            if not token:
                messagebox.showerror("号码提醒", "请填写提醒连接码。", parent=window)
                return
            raw_times = [part.strip() for part in re.split(r"[,，;；\s]+", reminder_times_var.get()) if part.strip()]
            if len(raw_times) > 5:
                messagebox.showerror("号码提醒", "定时提醒最多设置 5 个时间点。", parent=window)
                return
            reminder_times = []
            for value in raw_times:
                if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                    messagebox.showerror("号码提醒", f"提醒时间格式无效：{value}，请使用 HH:MM。", parent=window)
                    return
                if value not in reminder_times:
                    reminder_times.append(value)
            try:
                interval = max(10, min(120, int(interval_var.get())))
                protected = protect_secret(token)
            except Exception as exc:
                messagebox.showerror("号码提醒", f"保存连接码失败：{exc}", parent=window)
                return
            self.config.number_inbox.api_url = api_url
            self.config.number_inbox.protected_token = protected
            self.config.number_inbox.interval_seconds = interval
            self.config.number_inbox.last_seen_id = 0
            self.config.number_inbox.reminder_times = reminder_times
            self.config.save()
            window.destroy()
            if self.enabled_vars["number_inbox"].get():
                self._start_one("number_inbox")

        ttk.Button(frame, text="保存并连接", command=save_and_connect).grid(row=5, column=0, columnspan=2, sticky="e")

    def _sedentary_command(self, action: str) -> None:
        status = read_sedentary_status()
        if not status:
            messagebox.showinfo(
                "久坐助手",
                "当前内置久坐模块尚未启动或状态接口暂不可用。请在主界面点击“重新启动”，无需单独更新久坐模块。",
            )
            return
        try:
            send_sedentary_command(action)
        except OSError as exc:
            messagebox.showerror("久坐助手", f"无法发送控制命令：{exc}")
            return
        self.status_vars["sedentary"].set(sedentary_status_text(status))

    def _copy_sms_code(self) -> None:
        code = self.sms_code_var.get().strip()
        if not re.fullmatch(r"\d{4,8}", code):
            messagebox.showinfo("短信助手", "目前没有可复制的验证码。")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(code)
        self.status_vars["sms"].set("验证码已复制")
        self.root.withdraw()

    def _show_sms_settings(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("短信助手设置")
        window.geometry("610x370")
        window.resizable(False, False)
        frame = ttk.Frame(window, padding=20)
        frame.pack(fill="both", expand=True)

        server_var = tk.StringVar(value=self.config.sms.server_base)
        channel_var = tk.StringVar(value=self.config.sms.channel)
        try:
            current_token = unprotect_secret(self.config.sms.protected_token)
        except Exception:
            current_token = ""
        token_var = tk.StringVar(value=current_token)
        interval_var = tk.IntVar(value=self.config.sms.interval_seconds)

        fields = (("服务器地址", server_var, False), ("接收主题", channel_var, False), ("访问令牌", token_var, True))
        for row, (label, variable, secret) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=7)
            ttk.Entry(frame, textvariable=variable, show="●" if secret else "", width=53).grid(row=row, column=1, sticky="ew", padx=(12, 0), pady=7)
        ttk.Label(frame, text="重连间隔（秒）").grid(row=3, column=0, sticky="w", pady=7)
        ttk.Spinbox(frame, from_=5, to=30, textvariable=interval_var, width=8).grid(row=3, column=1, sticky="w", padx=(12, 0), pady=7)
        ttk.Label(frame, text="旧版短信助手配置会在首次运行时自动迁移；令牌继续使用 Windows 用户级加密保存。", style="Sub.TLabel", wraplength=540).grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 16))
        frame.columnconfigure(1, weight=1)

        def save_and_connect() -> None:
            server = server_var.get().strip().rstrip("/")
            channel = channel_var.get().strip().strip("/")
            token = token_var.get().strip()
            parsed = urlparse(server)
            if parsed.scheme.lower() != "https" or not parsed.netloc or parsed.path not in ("", "/"):
                messagebox.showerror("短信助手", "服务器地址应为 HTTPS 域名，例如 https://sms.example.com。", parent=window)
                return
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", channel):
                messagebox.showerror("短信助手", "接收主题只能包含字母、数字、横线或下划线。", parent=window)
                return
            if not token:
                messagebox.showerror("短信助手", "请填写访问令牌。", parent=window)
                return
            try:
                interval = max(5, min(30, int(interval_var.get())))
                protected = protect_secret(token)
            except Exception as exc:
                messagebox.showerror("短信助手", f"保存令牌失败：{exc}", parent=window)
                return
            self.config.sms.server_base = server
            self.config.sms.channel = channel
            self.config.sms.protected_token = protected
            self.config.sms.marker = "latest"
            self.config.sms.interval_seconds = interval
            self.config.save()
            window.destroy()
            if self.enabled_vars["sms"].get():
                self._start_one("sms")

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="发送测试", command=lambda: self._send_sms_test(server_var.get(), channel_var.get(), token_var.get())).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="保存并连接", command=save_and_connect).pack(side="left")

    def _send_sms_test(self, server: str, channel: str, token: str) -> None:
        if not token.strip():
            messagebox.showinfo("短信助手", "请先填写访问令牌。")
            return
        settings = type(self.config.sms)(
            server_base=server.strip().rstrip("/"),
            channel=channel.strip().strip("/"),
            interval_seconds=self.config.sms.interval_seconds,
        )
        self.sms_receiver.publish_test(settings, token.strip())
        self.status_vars["sms"].set("正在发送测试短信")

    def _show_update_progress(self, *, indeterminate: bool = False) -> None:
        bar = self.update_progress_bar
        bar.stop()
        bar.configure(mode="indeterminate" if indeterminate else "determinate")
        if not bar.winfo_manager():
            bar.pack(fill="x", pady=(8, 0))
        if indeterminate:
            bar.start(15)

    def _download_progress(self, received: int, total: int) -> None:
        percent = min(100, max(0, int(received * 100 / total))) if total > 0 else 0
        self.update_progress_var.set(percent)
        self._set_update_status(f"更新状态：正在下载 {percent}%（{received / 1048576:.1f} / {total / 1048576:.1f} MB）")

    def _update_phase(self, phase: str) -> None:
        self._show_update_progress(indeterminate=True)
        self._set_update_status(f"更新状态：{phase}")

    def _hide_update_progress(self) -> None:
        self.update_progress_bar.stop()
        self.update_progress_bar.pack_forget()
        self.update_progress_var.set(0)

    def _request_update_check(self) -> None:
        self._show_settings_page()
        if self._update_checking:
            self._set_update_status("更新状态：正在处理，请稍候", notify=True)
            return
        self._update_checking = True
        self._set_update_status("更新状态：正在检查新版本…", notify=True)
        self._check_updates()

    def _finish_update_check(self, status: str) -> None:
        self._update_checking = False
        self._hide_update_progress()
        self._set_update_status(status)

    def _check_updates(self) -> None:
        def worker() -> None:
            try:
                manifest = fetch_manifest()
                has_update = newer_version_available(__version__, manifest)
            except Exception as exc:
                def failed() -> None:
                    self._finish_update_check("更新状态：检查失败")
                    messagebox.showwarning("检查更新", f"无法检查 win-assistants 更新：{exc}")
                self.root.after(0, failed)
                return

            if not has_update:
                def current() -> None:
                    self._finish_update_check(f"更新状态：v{__version__} 已是最新版")
                    messagebox.showinfo(
                        "检查更新",
                        f"win-assistants v{__version__} 已是最新版。\n\n短信、久坐、Foxmail 与号码提醒均通过这一个“检查更新”统一更新。",
                    )
                self.root.after(0, current)
                return

            version = str(manifest.get("version", "")).strip()
            notes = str(manifest.get("notes", "")).strip()

            def confirm() -> None:
                self._set_update_status(f"更新状态：发现 v{version}")
                text = f"当前版本：v{__version__}\n目标版本：v{version}\n\n发现新的 win-assistants。"
                if notes:
                    text += f"\n\n{notes}"
                text += "\n\n是否现在下载并更新？\n整个 win-assistants.exe 会一次更新完成，下载、SHA256校验、替换和重启均自动执行。"
                if not messagebox.askyesno("发现更新", text):
                    self._finish_update_check("更新状态：已取消")
                    return
                self.update_progress_var.set(0)
                self._show_update_progress()
                self._set_update_status(f"更新状态：准备下载 v{version}…", notify=True)
                threading.Thread(
                    target=lambda: self._download_and_apply_update(manifest),
                    name="win-assistants-updater",
                    daemon=True,
                ).start()

            self.root.after(0, confirm)

        threading.Thread(target=worker, name="win-assistants-update-check", daemon=True).start()

    def _download_and_apply_update(self, manifest: dict[str, object]) -> None:
        try:
            def on_progress(received: int, total: int) -> None:
                self.root.after(0, lambda received=received, total=total:
                                self._download_progress(received, total))

            def on_phase(message: str) -> None:
                self.root.after(0, lambda message=message: self._update_phase(message))

            staged = stage_update(manifest, progress=on_progress, phase=on_phase)
            on_phase("正在验证新程序能否启动…")
            verify_staged_startup(staged)
            self.root.after(0, lambda: self._update_phase("校验完成，正在安装并重启…"))
            launch_replacement(staged, manifest)
        except Exception as exc:
            def failed() -> None:
                self._finish_update_check("更新状态：更新失败")
                messagebox.showerror("更新失败", str(exc))
            self.root.after(0, failed)
            return
        self.root.after(0, self._exit_for_update)

    def _toggle_startup(self) -> None:
        try:
            set_startup(bool(self.startup_var.get()))
        except Exception as exc:
            self.startup_var.set(False)
            messagebox.showerror("开机启动", str(exc))

    def _take_over(self) -> None:
        if not messagebox.askyesno("接管开机启动", "只删除三个旧工具的已知开机启动入口，不删除程序或设置。以后由 win-assistants 统一启动它们。是否继续？"):
            return
        try:
            removed = take_over_legacy_startup()
            stopped = stop_legacy_foxmail_processes()
            if self.enabled_vars["chen_helper"].get():
                self.foxmail_bridge.stop()
                _ok, bridge_detail = self.foxmail_bridge.start()
                self.status_vars["chen_helper"].set(bridge_detail)
            self.startup_var.set(True)
            detail = "、".join(removed) if removed else "未发现旧入口"
            running = f"；已停止 {stopped} 个旧 Foxmail 进程" if stopped else ""
            messagebox.showinfo("接管完成", f"win-assistants 已设为开机启动。\n处理结果：{detail}{running}")
        except Exception as exc:
            messagebox.showerror("接管失败", str(exc))

    def _start_tray(self) -> bool:
        try:
            import pystray
            from PIL import Image, ImageDraw

            image = Image.new("RGBA", (64, 64), GREEN)
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((7, 7, 57, 57), radius=13, fill=GREEN, outline="white", width=4)
            draw.text((18, 14), "W", fill="white")
            menu = pystray.Menu(
                pystray.MenuItem("打开 win-assistants", lambda *_args: self.ui_actions.put("show"), default=True),
                pystray.MenuItem("检查更新", lambda *_args: self.ui_actions.put("check_updates")),
                pystray.MenuItem("退出", lambda *_args: self.ui_actions.put("exit")),
            )
            self.tray_icon = pystray.Icon("win-assistants", image, "win-assistants", menu)
            self.tray_icon.run_detached()
            return True
        except Exception:
            self.tray_icon = None
            return False

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _shutdown(self) -> None:
        if self.number_reminder_window is not None and self.number_reminder_window.winfo_exists():
            self.number_reminder_window.destroy()
        self.number_reminder_window = None
        self.number_reminder_items.clear()
        self.sms_receiver.stop()
        self.foxmail_bridge.stop()
        self.number_inbox_receiver.stop()
        self.manager.stop_all()
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()

    def _exit_for_update(self) -> None:
        # A validated self-update must be able to close the current executable
        # even while the sedentary module is in a forced-rest state.
        self._shutdown()

    def _exit(self) -> None:
        status = read_sedentary_status()
        if status and bool(status.get("reminder_active")):
            messagebox.showwarning("强制休息中", "请先完成当前强制休息，再退出 win-assistants。")
            return
        self._shutdown()


def run() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--update-startup-probe", default="")
    args, _ = parser.parse_known_args()
    instance = SingleInstance()
    if instance.already_running:
        instance.close()
        return
    root = tk.Tk()
    try:
        WinAssistantsApp(root, start_hidden=args.background)
        if args.update_startup_probe:
            Path(args.update_startup_probe).write_text("ready", encoding="ascii")
        root.mainloop()
    finally:
        instance.close()

