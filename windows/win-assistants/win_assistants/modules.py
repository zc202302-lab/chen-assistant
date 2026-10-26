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
    ModuleDefinition("number_inbox", "号码提醒", "提醒同事新提交的待录入号码", 3),
    ModuleDefinition("work_todos", "待办事项", "独立待办同步、提醒、延期与结办", 3),
)


def _existing(*paths: Path) -> Path | None:
    return next((path for path in paths if path.exists()), None)


def internal_sedentary_command() -> list[str]:
    """Launch the mature sedentary runtime from this same win-assistants build."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--sedentary", "--embedded", "--startup"]

    root = Path(__file__).resolve().parent.parent
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    executable = pythonw if pythonw.exists() else Path(sys.executable)
    return [
        str(executable),
        str(root / "main.py"),
        "--sedentary",
        "--embedded",
        "--startup",
    ]


def default_module_configs() -> dict[str, ModuleConfig]:
    commands = {
        "sms": [],
        "work_todos": [],
        "sedentary": internal_sedentary_command(),
        "chen_helper": [],
        "number_inbox": [],
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

    def stop(self, key: str) -> None:
        process = self.processes.pop(key, None)
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=4)
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                except OSError:
                    pass
        self.status_callback(key, "已停用")

    def stop_all(self) -> None:
        for key in tuple(self.processes):
            self.stop(key)

    def refresh(self) -> None:
        for key in tuple(self.processes):
            self.status_callback(key, self.status(key))
