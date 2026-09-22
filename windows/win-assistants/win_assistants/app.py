from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .config import AppConfig
from .modules import MODULES, ModuleManager, default_module_configs
from .single_instance import SingleInstance
from .startup import is_startup_enabled, set_startup, take_over_legacy_startup


BG = "#F4F7F6"
CARD = "#FFFFFF"
GREEN = "#167D68"
TEXT = "#18332E"
MUTED = "#61736F"


def _display_path(command: list[str]) -> str:
    if not command:
        return ""
    for value in command:
        if value.lower().endswith((".exe", ".py", ".ps1")) and not value.lower().endswith(("python.exe", "pythonw.exe", "powershell.exe")):
            return value
    return command[0]


def _command_for_path(key: str, path: str) -> list[str]:
    suffix = Path(path).suffix.lower()
    if key == "sms":
        return [path, "--background"]
    if suffix == ".py":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        return [str(pythonw if pythonw.exists() else Path(sys.executable)), path, "--startup"]
    if suffix == ".ps1":
        return ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", path, "-Watch"]
    return [path, "--startup"] if key == "sedentary" else [path]


class WinAssistantsApp:
    def __init__(self, root: tk.Tk, start_hidden: bool = False) -> None:
        self.root = root
        self.config = AppConfig.load(default_module_configs())
        self.manager = ModuleManager(self._set_status)
        self.tray_icon = None
        self.status_vars = {item.key: tk.StringVar(value="等待启动") for item in MODULES}
        self.enabled_vars = {item.key: tk.BooleanVar(value=self.config.modules[item.key].enabled) for item in MODULES}
        self.path_vars = {
            item.key: tk.StringVar(value=_display_path(self.config.modules[item.key].command))
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
            ttk.Checkbutton(head, variable=self.enabled_vars[item.key], command=self._save_ui).pack(side="left")
            ttk.Label(head, text=item.name, style="Module.TLabel").pack(side="left")
            ttk.Label(head, textvariable=self.status_vars[item.key], style="Card.TLabel").pack(side="right")
            ttk.Label(card, text=item.description, style="Card.TLabel").pack(anchor="w", padx=(28, 0), pady=(3, 8))
            row = ttk.Frame(card, style="Card.TFrame")
            row.pack(fill="x", padx=(28, 0))
            ttk.Entry(row, textvariable=self.path_vars[item.key]).pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="选择", command=lambda key=item.key: self._choose_path(key)).pack(side="left", padx=(8, 0))
            ttk.Button(row, text="立即启动", command=lambda key=item.key: self._start_one(key)).pack(side="left", padx=(8, 0))

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(controls, text="win-assistants 随 Windows 登录启动", variable=self.startup_var, command=self._toggle_startup).pack(side="left")
        ttk.Button(controls, text="接管旧工具的开机启动", command=self._take_over).pack(side="right")
        ttk.Label(outer, text=f"v{__version__} · 第一阶段统一壳：功能逻辑保持原样，后续逐步内置为同一进程。", style="Sub.TLabel").pack(anchor="w", pady=(14, 0))

    def _save_ui(self) -> None:
        for item in MODULES:
            cfg = self.config.modules[item.key]
            cfg.enabled = bool(self.enabled_vars[item.key].get())
            path = self.path_vars[item.key].get().strip()
            if path:
                if path != _display_path(cfg.command):
                    cfg.command = _command_for_path(item.key, path)
            elif cfg.command:
                cfg.command = []
        self.config.save()

    def _choose_path(self, key: str) -> None:
        path = filedialog.askopenfilename(title="选择模块程序", filetypes=[("程序或脚本", "*.exe *.py *.ps1"), ("所有文件", "*.*")])
        if not path:
            return
        cfg = self.config.modules[key]
        cfg.command = _command_for_path(key, path)
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

    def _start_one(self, key: str) -> None:
        self._save_ui()
        ok, detail = self.manager.start(key, self.config.modules[key])
        self.status_vars[key].set(detail)

    def _set_status(self, key: str, status: str) -> None:
        variable = self.status_vars.get(key)
        if variable:
            variable.set(status)

    def _poll(self) -> None:
        self.manager.refresh()
        self.root.after(1500, self._poll)

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
            self.startup_var.set(True)
            detail = "、".join(removed) if removed else "未发现旧入口"
            messagebox.showinfo("接管完成", f"win-assistants 已设为开机启动。\n处理结果：{detail}")
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

    def _exit(self) -> None:
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()


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
