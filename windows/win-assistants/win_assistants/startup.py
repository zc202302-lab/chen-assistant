from __future__ import annotations

import os
import sys
from pathlib import Path


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "win-assistants"
LEGACY_RUN_VALUES = ("SedentaryReminder",)
LEGACY_SHORTCUTS = (
    "iPhone验证码助手-免部署版.lnk",
    "晨的助手-Foxmail桥接.lnk",
    "ChenAssistant-Foxmail-Helper.lnk",
)


def startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --background'
    root = Path(__file__).resolve().parent.parent
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    executable = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{executable}" "{root / "main.py"}" --background'


def is_startup_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except OSError:
        return False


def set_startup(enabled: bool) -> None:
    if sys.platform != "win32":
        raise RuntimeError("开机启动只支持 Windows。")
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass


def take_over_legacy_startup() -> list[str]:
    """Disable only known legacy startup entries; never delete installed programs."""
    if sys.platform != "win32":
        raise RuntimeError("开机启动接管只支持 Windows。")
    import winreg

    removed: list[str] = []
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        for value in LEGACY_RUN_VALUES:
            try:
                winreg.DeleteValue(key, value)
                removed.append(value)
            except FileNotFoundError:
                pass
    startup_dir = Path(os.getenv("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    for name in LEGACY_SHORTCUTS:
        path = startup_dir / name
        if path.exists():
            path.unlink()
            removed.append(name)
    set_startup(True)
    return removed
