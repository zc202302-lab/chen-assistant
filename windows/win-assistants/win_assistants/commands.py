from __future__ import annotations

import sys
from pathlib import Path


def display_path(command: list[str]) -> str:
    if not command:
        return ""
    for value in command:
        lowered = value.lower()
        if lowered.endswith((".exe", ".py", ".ps1")) and not lowered.endswith(
            ("python.exe", "pythonw.exe", "powershell.exe")
        ):
            return value
    return command[0]


def command_for_path(key: str, path: str) -> list[str]:
    suffix = Path(path).suffix.lower()
    if key == "sms":
        return [path, "--background"]
    if suffix == ".py":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        return [str(pythonw if pythonw.exists() else Path(sys.executable)), path, "--startup"]
    if suffix == ".ps1":
        return [
            "powershell.exe",
            "-NoProfile",
            "-STA",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            path,
            "-Watch",
        ]
    return [path, "--startup"] if key == "sedentary" else [path]
