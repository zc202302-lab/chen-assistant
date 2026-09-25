from __future__ import annotations

import os
import sys


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "SedentaryReminder"


def startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --startup'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    executable = pythonw if os.path.exists(pythonw) else sys.executable
    main = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))
    return f'"{executable}" "{main}" --startup'


def set_startup(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
