from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
import winreg

if sys.platform != "win32":
    raise SystemExit("仅支持 Windows。")

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:
    pystray = None
    Image = None
    ImageDraw = None

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_SHOWMAXIMIZED = 3
SW_RESTORE = 9

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

VK_SPACE = 0x20
VK_RETURN = 0x0D
VK_RIGHT = 0x27
VK_LEFT = 0x25
VK_ESCAPE = 0x1B

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

TARGET_PROCESS = "uSmartView_VDI_Client.exe"
TARGET_TITLE_FALLBACK = "我的电脑"

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "cloud_workspace_config.json"
AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "ChenCloudWorkspace"

DEFAULT_CONFIG = {
    "toggle": "Ctrl+Alt+Space",
    "maximize": "Ctrl+Alt+Enter",
    "dock_right": "Ctrl+Alt+Right",
    "dock_left": "Ctrl+Alt+Left",
    "minimize": "Ctrl+Alt+Esc",
    "start_minimized": True,
    "start_with_windows": False,
}

HOTKEYS = {
    1: ("toggle", "切到云电脑 / 返回"),
    2: ("maximize", "云电脑最大化"),
    3: ("dock_right", "停靠右侧"),
    4: ("dock_left", "停靠左侧"),
    5: ("minimize", "最小化并返回"),
}


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.MoveWindow.argtypes = [
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.BOOL,
]
user32.MoveWindow.restype = wintypes.BOOL
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [
    ctypes.POINTER(MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
user32.GetMessageW.restype = ctypes.c_int
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL

kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


KEY_NAME_TO_VK = {
    "SPACE": VK_SPACE,
    "ENTER": VK_RETURN,
    "RETURN": VK_RETURN,
    "RIGHT": VK_RIGHT,
    "LEFT": VK_LEFT,
    "ESC": VK_ESCAPE,
    "ESCAPE": VK_ESCAPE,
    **{chr(code): code for code in range(ord("A"), ord("Z") + 1)},
    **{str(n): ord(str(n)) for n in range(10)},
    **{f"F{n}": 0x6F + n for n in range(1, 13)},
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update({k: raw[k] for k in cfg.keys() if k in raw})
        except Exception:
            pass
    save_config(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{exe}" "{Path(__file__).resolve()}"'


def set_autostart(enabled: bool) -> None:
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        AUTOSTART_KEY,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            winreg.SetValueEx(
                key,
                AUTOSTART_NAME,
                0,
                winreg.REG_SZ,
                _autostart_command(),
            )
        else:
            try:
                winreg.DeleteValue(key, AUTOSTART_NAME)
            except FileNotFoundError:
                pass


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            AUTOSTART_KEY,
            0,
            winreg.KEY_QUERY_VALUE,
        ) as key:
            value, _ = winreg.QueryValueEx(key, AUTOSTART_NAME)
            return bool(value)
    except FileNotFoundError:
        return False


def normalize_hotkey(text: str) -> str:
    parts = [p.strip() for p in text.replace("＋", "+").split("+") if p.strip()]
    mods = []
    key = None
    for part in parts:
        upper = part.upper()
        if upper in {"CTRL", "CONTROL"}:
            if "Ctrl" not in mods:
                mods.append("Ctrl")
        elif upper == "ALT":
            if "Alt" not in mods:
                mods.append("Alt")
        elif upper == "SHIFT":
            if "Shift" not in mods:
                mods.append("Shift")
        elif upper in {"WIN", "WINDOWS", "META"}:
            if "Win" not in mods:
                mods.append("Win")
        else:
            if key is not None:
                raise ValueError("只能设置一个主按键")
            key = upper
    if key is None:
        raise ValueError("缺少主按键")
    if key not in KEY_NAME_TO_VK:
        raise ValueError(
            "主按键支持 A-Z、0-9、F1-F12、Space、Enter、Left、Right、Esc"
        )
    return "+".join(mods + [key.title() if key in {"SPACE", "ENTER", "RIGHT", "LEFT", "ESC"} else key])


def parse_hotkey(text: str) -> tuple[int, int]:
    normalized = normalize_hotkey(text)
    parts = normalized.split("+")
    modifiers = 0
    key = parts[-1].upper()
    for part in parts[:-1]:
        upper = part.upper()
        if upper == "CTRL":
            modifiers |= MOD_CONTROL
        elif upper == "ALT":
            modifiers |= MOD_ALT
        elif upper == "SHIFT":
            modifiers |= MOD_SHIFT
        elif upper == "WIN":
            modifiers |= MOD_WIN
    return modifiers, KEY_NAME_TO_VK[key]


def get_window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


def process_name_from_hwnd(hwnd: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value.rsplit("\\", 1)[-1]
    finally:
        kernel32.CloseHandle(handle)


def find_target_window() -> int | None:
    matches: list[int] = []

    @EnumWindowsProc
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = get_window_title(hwnd)
        pname = process_name_from_hwnd(hwnd)
        if pname.lower() == TARGET_PROCESS.lower():
            matches.append(hwnd)
        elif TARGET_TITLE_FALLBACK in title:
            matches.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    if not matches:
        return None

    fg = user32.GetForegroundWindow()
    if fg in matches:
        return fg
    for hwnd in matches:
        if not user32.IsIconic(hwnd):
            return hwnd
    return matches[0]


def monitor_work_area(hwnd: int) -> RECT:
    monitor = user32.MonitorFromWindow(hwnd, 2)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return info.rcWork


def bring_to_front(hwnd: int) -> None:
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.04)
    else:
        user32.ShowWindow(hwnd, SW_SHOWNORMAL)
    user32.SetForegroundWindow(hwnd)


class Switcher:
    def __init__(self):
        self.previous_hwnd: int | None = None

    def _target(self) -> int | None:
        return find_target_window()

    def toggle(self):
        target = self._target()
        if not target:
            return False, "未找到移动云电脑窗口，请先打开“我的电脑”云电脑会话。"
        fg = user32.GetForegroundWindow()
        if fg == target and self.previous_hwnd:
            prev = self.previous_hwnd
            self.previous_hwnd = None
            user32.ShowWindow(prev, SW_RESTORE)
            user32.SetForegroundWindow(prev)
            return True, "已返回本机窗口"
        if fg and fg != target:
            self.previous_hwnd = fg
        bring_to_front(target)
        return True, "已切到云电脑"

    def maximize(self):
        target = self._target()
        if not target:
            return False, "未找到云电脑窗口"
        user32.ShowWindow(target, SW_SHOWMAXIMIZED)
        user32.SetForegroundWindow(target)
        return True, "云电脑已最大化"

    def dock(self, side: str):
        target = self._target()
        if not target:
            return False, "未找到云电脑窗口"
        user32.ShowWindow(target, SW_RESTORE)
        time.sleep(0.03)
        area = monitor_work_area(target)
        width = area.right - area.left
        height = area.bottom - area.top
        dock_width = int(width * 0.62)
        x = area.right - dock_width if side == "right" else area.left
        user32.MoveWindow(target, x, area.top, dock_width, height, True)
        user32.SetForegroundWindow(target)
        return True, "云电脑已停靠"

    def minimize(self):
        target = self._target()
        if not target:
            return False, "未找到云电脑窗口"
        user32.ShowWindow(target, SW_SHOWMINIMIZED)
        if self.previous_hwnd:
            user32.SetForegroundWindow(self.previous_hwnd)
        return True, "云电脑已最小化"


class HotkeyEngine:
    def __init__(self, switcher: Switcher, events: queue.Queue):
        self.switcher = switcher
        self.events = events
        self.thread: threading.Thread | None = None
        self.thread_id: int | None = None
        self.stop_event = threading.Event()
        self.config: dict | None = None

    def start(self, config: dict) -> None:
        self.stop()
        self.stop_event.clear()
        self.config = dict(config)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.thread and self.thread.is_alive() and self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
            self.thread.join(timeout=1.5)
        self.thread = None
        self.thread_id = None

    def _run(self) -> None:
        self.thread_id = kernel32.GetCurrentThreadId()
        registered = []
        try:
            for hotkey_id, (key, _) in HOTKEYS.items():
                text = str(self.config[key])
                modifiers, vk = parse_hotkey(text)
                if not user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, vk):
                    raise RuntimeError(f"快捷键冲突或已被占用：{text}")
                registered.append(hotkey_id)
            self.events.put(("ready", "快捷键已启用"))
            msg = MSG()
            while True:
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                if msg.message != WM_HOTKEY:
                    continue
                hotkey_id = int(msg.wParam)
                if hotkey_id == 1:
                    ok, text = self.switcher.toggle()
                elif hotkey_id == 2:
                    ok, text = self.switcher.maximize()
                elif hotkey_id == 3:
                    ok, text = self.switcher.dock("right")
                elif hotkey_id == 4:
                    ok, text = self.switcher.dock("left")
                elif hotkey_id == 5:
                    ok, text = self.switcher.minimize()
                else:
                    continue
                self.events.put(("status", text))
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            for hotkey_id in registered:
                user32.UnregisterHotKey(None, hotkey_id)
            self.thread_id = None


class SettingsApp:
    def __init__(self):
        self.config = load_config()
        if self.config.get("start_with_windows"):
            try:
                set_autostart(True)
            except OSError:
                pass
        self.switcher = Switcher()
        self.events: queue.Queue = queue.Queue()
        self.engine = HotkeyEngine(self.switcher, self.events)
        self.root = tk.Tk()
        self.root.title("晨的小助手 · 云电脑快捷切换")
        self.root.geometry("520x445")
        self.root.minsize(490, 420)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.status_var = tk.StringVar(value="正在启动…")
        self.vars: dict[str, tk.StringVar] = {}
        self.tray = None
        self._build_ui()
        self._start_engine()
        self.root.after(150, self._poll_events)
        self._start_tray()
        if self.config.get("start_minimized") and self.tray is not None:
            self.root.after(350, self.hide_window)

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=18)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="云电脑快捷切换",
            font=("Microsoft YaHei UI", 16, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text="点击输入框后，直接按下你想使用的快捷键组合。",
        ).pack(anchor="w", pady=(4, 14))

        grid = ttk.Frame(frame)
        grid.pack(fill="x")
        for row, (hotkey_id, (key, label)) in enumerate(HOTKEYS.items()):
            ttk.Label(grid, text=label, width=18).grid(row=row, column=0, sticky="w", pady=6)
            var = tk.StringVar(value=str(self.config[key]))
            self.vars[key] = var
            entry = ttk.Entry(grid, textvariable=var, width=28)
            entry.grid(row=row, column=1, sticky="ew", pady=6)
            entry.bind("<KeyPress>", lambda e, k=key: self._capture_key(e, k))
        grid.columnconfigure(1, weight=1)

        self.start_minimized_var = tk.BooleanVar(
            value=bool(self.config.get("start_minimized", True))
        )
        ttk.Checkbutton(
            frame,
            text="启动后隐藏到系统托盘",
            variable=self.start_minimized_var,
        ).pack(anchor="w", pady=(14, 4))

        self.start_with_windows_var = tk.BooleanVar(
            value=bool(self.config.get("start_with_windows", False) or autostart_enabled())
        )
        ttk.Checkbutton(
            frame,
            text="Windows 登录后自动启动",
            variable=self.start_with_windows_var,
        ).pack(anchor="w", pady=(2, 6))

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(14, 8))
        ttk.Button(buttons, text="保存并应用", command=self.save_and_apply).pack(side="left")
        ttk.Button(buttons, text="测试切换", command=self.test_toggle).pack(side="left", padx=8)
        ttk.Button(buttons, text="隐藏到托盘", command=self.hide_window).pack(side="left")
        ttk.Button(buttons, text="退出", command=self.quit_app).pack(side="right")

        ttk.Separator(frame).pack(fill="x", pady=12)
        ttk.Label(frame, textvariable=self.status_var).pack(anchor="w")
        ttk.Label(
            frame,
            text="目标窗口：uSmartView_VDI_Client.exe / “我的电脑”",
            foreground="#666666",
        ).pack(anchor="w", pady=(7, 0))

    def _capture_key(self, event, key: str):
        ignored = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Win_L", "Win_R"}
        if event.keysym in ignored:
            return "break"

        parts = []
        state = int(event.state)
        if state & 0x0004:
            parts.append("Ctrl")
        if state & 0x0008 or state & 0x20000:
            parts.append("Alt")
        if state & 0x0001:
            parts.append("Shift")

        keysym = event.keysym
        mapping = {
            "space": "Space",
            "Return": "Enter",
            "Escape": "Esc",
            "Left": "Left",
            "Right": "Right",
        }
        main = mapping.get(keysym, keysym.upper())
        if main in {"CONTROL_L", "CONTROL_R", "SHIFT_L", "SHIFT_R", "ALT_L", "ALT_R"}:
            return "break"
        parts.append(main)
        self.vars[key].set("+".join(parts))
        return "break"

    def _start_engine(self):
        try:
            for key, _ in HOTKEYS.values():
                self.config[key] = normalize_hotkey(str(self.config[key]))
            self.engine.start(self.config)
        except Exception as exc:
            self.status_var.set(str(exc))

    def save_and_apply(self):
        new_cfg = dict(self.config)
        try:
            seen = set()
            for key, _ in HOTKEYS.values():
                normalized = normalize_hotkey(self.vars[key].get())
                signature = parse_hotkey(normalized)
                if signature in seen:
                    raise ValueError(f"存在重复快捷键：{normalized}")
                seen.add(signature)
                new_cfg[key] = normalized
            new_cfg["start_minimized"] = bool(self.start_minimized_var.get())
            new_cfg["start_with_windows"] = bool(self.start_with_windows_var.get())
        except Exception as exc:
            messagebox.showerror("快捷键设置错误", str(exc), parent=self.root)
            return

        self.engine.stop()
        self.config = new_cfg
        save_config(self.config)
        try:
            set_autostart(bool(self.config.get("start_with_windows")))
        except OSError as exc:
            messagebox.showerror("开机启动设置失败", str(exc), parent=self.root)
        self.engine.start(self.config)
        self.status_var.set("设置已保存，正在重新启用快捷键…")

    def test_toggle(self):
        ok, text = self.switcher.toggle()
        self.status_var.set(text)
        if not ok:
            messagebox.showwarning("云电脑未找到", text, parent=self.root)

    def show_window(self, *_):
        self.root.after(0, self._show_window_ui)

    def _show_window_ui(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self):
        if self.tray is None:
            self.root.iconify()
        else:
            self.root.withdraw()

    def _make_tray_icon(self):
        image = Image.new("RGB", (64, 64), "white")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((6, 6, 58, 58), radius=12, fill="#111827")
        draw.rectangle((15, 17, 49, 40), fill="#ffffff")
        draw.rectangle((27, 41, 37, 47), fill="#ffffff")
        draw.rectangle((21, 48, 43, 52), fill="#ffffff")
        return image

    def _start_tray(self):
        if pystray is None:
            self.status_var.set("托盘组件未安装；快捷键仍可使用，窗口会最小化运行。")
            return
        menu = pystray.Menu(
            pystray.MenuItem("显示设置", self.show_window, default=True),
            pystray.MenuItem("切到云电脑 / 返回", lambda *_: self.root.after(0, self.test_toggle)),
            pystray.MenuItem("退出", lambda *_: self.root.after(0, self.quit_app)),
        )
        self.tray = pystray.Icon(
            "chen_cloud_workspace",
            self._make_tray_icon(),
            "晨的小助手 · 云电脑切换",
            menu,
        )
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _poll_events(self):
        try:
            while True:
                kind, text = self.events.get_nowait()
                self.status_var.set(text)
                if kind == "error":
                    self.root.deiconify()
                    messagebox.showerror("快捷键启用失败", text, parent=self.root)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_events)

    def quit_app(self):
        self.engine.stop()
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    SettingsApp().run()


if __name__ == "__main__":
    main()
