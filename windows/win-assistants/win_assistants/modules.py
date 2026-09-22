from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import ModuleConfig


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0)


@dataclass(frozen=True)
class ModuleDefinition:
    key: str
    name: str
    description: str
    default_delay: int


MODULES = (
    ModuleDefinition("sms", "短信助手", "接收 iPhone 短信并提取验证码", 1),
    ModuleDefinition("sedentary", "久坐助手", "摄像头人体检测与强制休息", 5),
    ModuleDefinition("chen_helper", "小助手连接", "Foxmail 与本机能力桥接", 2),
)


def _existing(*paths: Path) -> Path | None:
    return next((path for path in paths if path.exists()), None)


def _sedentary_command() -> list[str]:
    roots = [
        Path(r"D:\Tools\chen-sit-guard"),
        Path(r"C:\Tools\chen-sit-guard"),
        Path.cwd().parent / "chen-sit-guard",
    ]
    for root in roots:
        executable = _existing(root / "晨·久坐守护.exe", root / "dist" / "晨·久坐守护.exe")
        if executable:
            return [str(executable), "--startup"]
        main = root / "main.py"
        pythonw = _existing(root / ".venv" / "Scripts" / "pythonw.exe", root / ".venv" / "Scripts" / "python.exe")
        if main.exists() and pythonw:
            return [str(pythonw), str(main), "--startup"]
    return []


def default_module_configs() -> dict[str, ModuleConfig]:
    commands = {
        "sms": [],
        "sedentary": _sedentary_command(),
        "chen_helper": [],
    }
    return {
        item.key: ModuleConfig(enabled=True, command=commands[item.key], delay_seconds=item.default_delay)
        for item in MODULES
    }


class ModuleManager:
    def __init__(self, status_callback: Callable[[str, str], None] | None = None) -> None:
        self.processes: dict[str, subprocess.Popen] = {}
        self.status_callback = status_callback or (lambda _key, _status: None)

    def status(self, key: str) -> str:
        process = self.processes.get(key)
        if process is None:
            return "未启动"
        if process.poll() is None:
            return "运行中"
        return f"已退出（{process.returncode}）"

    def start(self, key: str, config: ModuleConfig) -> tuple[bool, str]:
        running = self.processes.get(key)
        if running is not None and running.poll() is None:
            return True, "已经运行"
        if not config.command:
            return False, "尚未设置程序路径"
        executable = config.command[0]
        if ("\\" in executable or "/" in executable) and not Path(executable).exists():
            return False, f"找不到程序：{executable}"
        try:
            flags = CREATE_NO_WINDOW
            if sys.platform == "win32":
                flags |= DETACHED_PROCESS
            process = subprocess.Popen(
                config.command,
                cwd=str(Path(executable).parent) if Path(executable).exists() else None,
                close_fds=True,
                creationflags=flags,
            )
            self.processes[key] = process
            self.status_callback(key, "运行中")
            return True, "已启动"
        except OSError as exc:
            self.status_callback(key, "启动失败")
            return False, f"启动失败：{exc}"

    def refresh(self) -> None:
        for key in tuple(self.processes):
            self.status_callback(key, self.status(key))
