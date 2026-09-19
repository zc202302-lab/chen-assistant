from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
import time

if sys.platform != "win32":
    raise SystemExit("仅支持 Windows。")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_SHOWMAXIMIZED = 3
SW_RESTORE = 9

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

VK_SPACE = 0x20
VK_RETURN = 0x0D
VK_RIGHT = 0x27
VK_LEFT = 0x25
VK_ESCAPE = 0x1B

WM_HOTKEY = 0x0312
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

TARGET_PROCESS = "uSmartView_VDI_Client.exe"
TARGET_TITLE_FALLBACK = "我的电脑"

HOTKEY_TOGGLE = 1
HOTKEY_MAXIMIZE = 2
HOTKEY_DOCK_RIGHT = 3
HOTKEY_DOCK_LEFT = 4
HOTKEY_MINIMIZE = 5


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
user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
user32.MoveWindow.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


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
            return True
        if TARGET_TITLE_FALLBACK and TARGET_TITLE_FALLBACK in title:
            matches.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    if not matches:
        return None

    fg = user32.GetForegroundWindow()
    if fg in matches:
        return fg

    # Prefer a non-minimized visible target if there are multiple windows.
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


def bring_to_front(hwnd: int):
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.05)
    else:
        user32.ShowWindow(hwnd, SW_SHOWNORMAL)
    user32.SetForegroundWindow(hwnd)


def maximize(hwnd: int):
    user32.ShowWindow(hwnd, SW_SHOWMAXIMIZED)
    user32.SetForegroundWindow(hwnd)


def dock(hwnd: int, side: str):
    user32.ShowWindow(hwnd, SW_RESTORE)
    time.sleep(0.03)
    area = monitor_work_area(hwnd)
    width = area.right - area.left
    height = area.bottom - area.top
    dock_width = int(width * 0.62)
    if side == "right":
        x = area.right - dock_width
    else:
        x = area.left
    user32.MoveWindow(hwnd, x, area.top, dock_width, height, True)
    user32.SetForegroundWindow(hwnd)


def minimize(hwnd: int):
    user32.ShowWindow(hwnd, SW_SHOWMINIMIZED)


class Switcher:
    def __init__(self):
        self.previous_hwnd: int | None = None

    def toggle(self):
        target = find_target_window()
        if not target:
            print("未找到移动云电脑窗口：请先打开“我的电脑”云电脑会话。")
            return

        fg = user32.GetForegroundWindow()
        if fg == target and self.previous_hwnd:
            prev = self.previous_hwnd
            self.previous_hwnd = None
            user32.ShowWindow(prev, SW_RESTORE)
            user32.SetForegroundWindow(prev)
            return

        if fg and fg != target:
            self.previous_hwnd = fg
        bring_to_front(target)

    def do_maximize(self):
        target = find_target_window()
        if target:
            maximize(target)

    def do_dock(self, side: str):
        target = find_target_window()
        if target:
            dock(target, side)

    def do_minimize(self):
        target = find_target_window()
        if target:
            minimize(target)
            if self.previous_hwnd:
                user32.SetForegroundWindow(self.previous_hwnd)


def register_hotkey(hotkey_id: int, modifiers: int, vk: int, label: str):
    if not user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, vk):
        raise RuntimeError(f"快捷键注册失败：{label}。可能已被其他软件占用。")


def main():
    switcher = Switcher()

    register_hotkey(HOTKEY_TOGGLE, MOD_CONTROL | MOD_ALT, VK_SPACE, "Ctrl+Alt+Space")
    register_hotkey(HOTKEY_MAXIMIZE, MOD_CONTROL | MOD_ALT, VK_RETURN, "Ctrl+Alt+Enter")
    register_hotkey(HOTKEY_DOCK_RIGHT, MOD_CONTROL | MOD_ALT, VK_RIGHT, "Ctrl+Alt+Right")
    register_hotkey(HOTKEY_DOCK_LEFT, MOD_CONTROL | MOD_ALT, VK_LEFT, "Ctrl+Alt+Left")
    register_hotkey(HOTKEY_MINIMIZE, MOD_CONTROL | MOD_ALT, VK_ESCAPE, "Ctrl+Alt+Esc")

    print("=" * 70)
    print("晨的小助手 · 云电脑工作区切换器")
    print("目标：uSmartView_VDI_Client.exe / 窗口“我的电脑”")
    print()
    print("Ctrl + Alt + Space  ：切到云电脑 / 再按一次返回刚才窗口")
    print("Ctrl + Alt + Enter  ：云电脑最大化")
    print("Ctrl + Alt + Right  ：云电脑停靠屏幕右侧约 62%")
    print("Ctrl + Alt + Left   ：云电脑停靠屏幕左侧约 62%")
    print("Ctrl + Alt + Esc    ：最小化云电脑并返回本机")
    print()
    print("关闭这个窗口即可停止快捷键。")
    print("=" * 70)

    msg = MSG()
    try:
        while True:
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result <= 0:
                break
            if msg.message != WM_HOTKEY:
                continue
            if msg.wParam == HOTKEY_TOGGLE:
                switcher.toggle()
            elif msg.wParam == HOTKEY_MAXIMIZE:
                switcher.do_maximize()
            elif msg.wParam == HOTKEY_DOCK_RIGHT:
                switcher.do_dock("right")
            elif msg.wParam == HOTKEY_DOCK_LEFT:
                switcher.do_dock("left")
            elif msg.wParam == HOTKEY_MINIMIZE:
                switcher.do_minimize()
    finally:
        for hotkey_id in (
            HOTKEY_TOGGLE,
            HOTKEY_MAXIMIZE,
            HOTKEY_DOCK_RIGHT,
            HOTKEY_DOCK_LEFT,
            HOTKEY_MINIMIZE,
        ):
            user32.UnregisterHotKey(None, hotkey_id)


if __name__ == "__main__":
    main()
