from __future__ import annotations

import argparse
import queue
import re
import threading
import tkinter as tk
from urllib.parse import urlparse
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .commands import command_for_path, display_path
from .config import AppConfig
from .foxmail import FoxmailBridge
from .modules import MODULES, ModuleManager, default_module_configs, internal_sedentary_command
from .number_inbox import NumberInboxReceiver
from .single_instance import SingleInstance
from .sms import SmsReceiver, migrate_legacy_config, protect_secret, unprotect_secret
from .sedentary import read_status as read_sedentary_status, send_command as send_sedentary_command, status_text as sedentary_status_text
from .startup import is_startup_enabled, set_startup, stop_legacy_foxmail_processes, take_over_legacy_startup
from .updater import fetch_manifest, launch_replacement, newer_version_available, stage_update


BG = "#F4F7F6"
CARD = "#FFFFFF"
GREEN = "#167D68"
TEXT = "#18332E"
MUTED = "#61736F"


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
        self.tray_icon = None
        self.sms_code_var = tk.StringVar(value="尚未收到验证码")
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
        self.root.after(1000, self._poll)

    def _configure_window(self) -> None:
        self.root.title("win-assistants")
        self.root.geometry("760x540")
        self.root.minsize(680, 480)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.root.withdraw)

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 22, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("Microsoft YaHei UI", 10))
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Module.TLabel", background=CARD, foreground=TEXT, font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("TButton", font=("Microsoft YaHei UI", 9), padding=6)

        outer = ttk.Frame(self.root, padding=24)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="win-assistants", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="一个入口管理短信、久坐与晨的小助手本地能力", style="Sub.TLabel").pack(anchor="w", pady=(2, 18))

        for item in MODULES:
            card = ttk.Frame(outer, style="Card.TFrame", padding=14)
            card.pack(fill="x", pady=(0, 10))
            head = ttk.Frame(card, style="Card.TFrame")
            head.pack(fill="x")
            ttk.Checkbutton(head, variable=self.enabled_vars[item.key], command=lambda key=item.key: self._toggle_module(key)).pack(side="left")
            ttk.Label(head, text=item.name, style="Module.TLabel").pack(side="left")
            ttk.Label(head, textvariable=self.status_vars[item.key], style="Card.TLabel").pack(side="right")
            ttk.Label(card, text=item.description, style="Card.TLabel").pack(anchor="w", padx=(28, 0), pady=(3, 8))
            row = ttk.Frame(card, style="Card.TFrame")
            row.pack(fill="x", padx=(28, 0))
            if item.key == "sms":
                ttk.Label(row, text="内置模块 · 不再启动独立短信 EXE", style="Card.TLabel").pack(side="left")
                ttk.Label(row, textvariable=self.sms_code_var, style="Card.TLabel").pack(side="left", padx=(18, 0))
                ttk.Button(row, text="复制验证码", command=self._copy_sms_code).pack(side="right", padx=(8, 0))
                ttk.Button(row, text="设置", command=self._show_sms_settings).pack(side="right")
            elif item.key == "chen_helper":
                ttk.Label(row, text="内置模块 · 仅监听 127.0.0.1:18763 · 不自动发送邮件", style="Card.TLabel").pack(side="left")
                ttk.Button(row, text="重新启动", command=lambda: self._start_one("chen_helper")).pack(side="right")
            elif item.key == "number_inbox":
                ttk.Label(row, text="内置模块 · 从晨的小助手读取待录入队列", style="Card.TLabel").pack(side="left")
                ttk.Button(row, text="打开待录入", command=self._open_number_inbox).pack(side="right", padx=(8, 0))
                ttk.Button(row, text="设置", command=self._show_number_inbox_settings).pack(side="right")
            elif item.key == "sedentary":
                ttk.Label(row, text="内置模块 · 人体存在检测与强制休息已合并", style="Card.TLabel").pack(side="left")
                ttk.Button(row, text="打开状态", command=lambda: self._sedentary_command("show_status")).pack(side="right", padx=(8, 0))
                ttk.Button(row, text="设置", command=lambda: self._sedentary_command("show_settings")).pack(side="right", padx=(8, 0))
                ttk.Button(row, text="重新启动", command=lambda key=item.key: self._restart_sedentary(key)).pack(side="right")
            else:
                ttk.Entry(row, textvariable=self.path_vars[item.key]).pack(side="left", fill="x", expand=True)
                ttk.Button(row, text="选择", command=lambda key=item.key: self._choose_path(key)).pack(side="left", padx=(8, 0))
                ttk.Button(row, text="立即启动", command=lambda key=item.key: self._start_one(key)).pack(side="left", padx=(8, 0))

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(6, 0))
        ttk.Label(controls, text=f"当前版本 v{__version__}", style="Sub.TLabel").pack(side="left", padx=(0, 12))
        ttk.Checkbutton(controls, text="随 Windows 登录静默启动（直接进入托盘）", variable=self.startup_var, command=self._toggle_startup).pack(side="left")
        ttk.Button(controls, text="检查更新", command=self._check_updates).pack(side="right")
        ttk.Button(controls, text="接管旧工具的开机启动", command=self._take_over).pack(side="right", padx=(0, 8))
        ttk.Label(outer, text=f"v{__version__} · 短信、久坐、Foxmail 与号码提醒均已内置。", style="Sub.TLabel").pack(anchor="w", pady=(14, 0))

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
            if inbox_event.item_id > self.config.number_inbox.last_seen_id:
                self.config.number_inbox.last_seen_id = inbox_event.item_id
                self.config.save()
            if inbox_event.kind == "new":
                detail = inbox_event.number
                if inbox_event.submitter:
                    detail += f" · {inbox_event.submitter}"
                if self.tray_icon is not None:
                    try:
                        self.tray_icon.notify(detail, "新的待录入号码")
                    except Exception:
                        self.root.bell()
                else:
                    self.root.bell()
                self._show_window()
        self.root.after(1500, self._poll)

    def _open_number_inbox(self) -> None:
        import webbrowser
        webbrowser.open("https://assistant.ziboxiaozhushou.cn/work/number-inbox")

    def _show_number_inbox_settings(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("号码提醒设置")
        window.geometry("650x330")
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

        ttk.Label(frame, text="服务器地址").grid(row=0, column=0, sticky="w", pady=7)
        ttk.Entry(frame, textvariable=api_var, width=57).grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=7)
        ttk.Label(frame, text="提醒连接码").grid(row=1, column=0, sticky="w", pady=7)
        ttk.Entry(frame, textvariable=token_var, show="●", width=57).grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=7)
        ttk.Label(frame, text="检查间隔（秒）").grid(row=2, column=0, sticky="w", pady=7)
        ttk.Spinbox(frame, from_=10, to=120, textvariable=interval_var, width=8).grid(row=2, column=1, sticky="w", padx=(12, 0), pady=7)
        ttk.Label(
            frame,
            text="连接码在网页“工作 → 号码收集 → Windows 提醒连接”中复制。只读取待处理号码，不会自动录入或改变状态。",
            style="Sub.TLabel",
            wraplength=570,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(12, 18))
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
            self.config.save()
            window.destroy()
            if self.enabled_vars["number_inbox"].get():
                self._start_one("number_inbox")

        ttk.Button(frame, text="保存并连接", command=save_and_connect).grid(row=4, column=0, columnspan=2, sticky="e")

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

    def _check_updates(self) -> None:
        self.status_vars["sedentary"].set(self.status_vars["sedentary"].get())
        def worker() -> None:
            try:
                manifest = fetch_manifest()
                has_update = newer_version_available(__version__, manifest)
            except Exception as exc:
                self.root.after(0, lambda: messagebox.showwarning("检查更新", f"无法检查 win-assistants 更新：{exc}"))
                return

            if not has_update:
                self.root.after(
                    0,
                    lambda: messagebox.showinfo(
                        "检查更新",
                        f"win-assistants v{__version__} 已是最新版。\n\n短信、久坐、Foxmail 与号码提醒均通过这一个“检查更新”统一更新。",
                    ),
                )
                return

            version = str(manifest.get("version", "")).strip()
            notes = str(manifest.get("notes", "")).strip()
            def confirm() -> None:
                text = f"当前版本：v{__version__}\n目标版本：v{version}\n\n发现新的 win-assistants。"
                if notes:
                    text += f"\n\n{notes}"
                text += "\n\n是否现在下载并更新？\n整个 win-assistants.exe 会一次更新完成，下载、SHA256校验、替换和重启均自动执行。"
                if not messagebox.askyesno("发现更新", text):
                    return
                threading.Thread(target=lambda: self._download_and_apply_update(manifest), name="win-assistants-updater", daemon=True).start()
            self.root.after(0, confirm)

        threading.Thread(target=worker, name="win-assistants-update-check", daemon=True).start()

    def _download_and_apply_update(self, manifest: dict[str, object]) -> None:
        try:
            staged = stage_update(manifest)
            launch_replacement(staged, manifest)
        except Exception as exc:
            self.root.after(0, lambda: messagebox.showerror("更新失败", str(exc)))
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
                pystray.MenuItem("打开 win-assistants", lambda: self.root.after(0, self._show_window), default=True),
                pystray.MenuItem("检查更新", lambda: self.root.after(0, self._check_updates)),
                pystray.MenuItem("退出", lambda: self.root.after(0, self._exit)),
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
    args, _ = parser.parse_known_args()
    instance = SingleInstance()
    if instance.already_running:
        instance.close()
        return
    root = tk.Tk()
    try:
        WinAssistantsApp(root, start_hidden=args.background)
        root.mainloop()
    finally:
        instance.close()
