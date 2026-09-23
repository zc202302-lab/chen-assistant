from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path


APP_DIR_NAME = "久坐提醒"
STATUS_FILE = "runtime-status.json"
COMMAND_FILE = "control-command.json"


def app_data_dir() -> Path:
    base = os.getenv("APPDATA") or str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME


def read_status(max_age_seconds: float = 8.0) -> dict[str, object] | None:
    path = app_data_dir() / STATUS_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        updated_at = float(raw.get("updated_at", 0))
        if updated_at <= 0 or time.time() - updated_at > max_age_seconds:
            return None
        return raw
    except (OSError, ValueError, TypeError):
        return None


def send_command(action: str) -> str:
    if action not in {"show_status", "show_settings"}:
        raise ValueError("unsupported sedentary command")
    directory = app_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / COMMAND_FILE
    temp = path.with_suffix(".tmp")
    command_id = uuid.uuid4().hex
    temp.write_text(
        json.dumps(
            {"id": command_id, "action": action, "created_at": time.time()},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    temp.replace(path)
    return command_id


def status_text(status: dict[str, object]) -> str:
    title = str(status.get("status") or "运行中")
    work_seconds = max(0.0, float(status.get("work_seconds", 0) or 0))
    away_seconds = max(0.0, float(status.get("away_seconds", 0) or 0))
    if title == "已休息":
        return f"已休息 · {int(away_seconds // 60)} 分钟"
    if title == "检测异常":
        return "检测异常"
    return f"工作中 · {int(work_seconds // 60)} 分钟"
