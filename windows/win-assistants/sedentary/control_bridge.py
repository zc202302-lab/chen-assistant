from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from .storage import app_data_dir


STATUS_FILE = "runtime-status.json"
COMMAND_FILE = "control-command.json"
MAX_STATUS_AGE_SECONDS = 8.0


def status_path() -> Path:
    return app_data_dir() / STATUS_FILE


def command_path() -> Path:
    return app_data_dir() / COMMAND_FILE


def write_runtime_status(payload: dict[str, object]) -> None:
    path = status_path()
    temp = path.with_suffix(".tmp")
    data = dict(payload)
    data["pid"] = os.getpid()
    data["updated_at"] = time.time()
    temp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(path)


def read_runtime_status(max_age_seconds: float = MAX_STATUS_AGE_SECONDS) -> dict[str, object] | None:
    path = status_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        updated_at = float(raw.get("updated_at", 0))
        if updated_at <= 0 or time.time() - updated_at > max_age_seconds:
            return None
        return raw
    except (OSError, ValueError, TypeError):
        return None


def send_control_command(action: str) -> str:
    if action not in {"show_status", "show_settings", "check_update"}:
        raise ValueError("unsupported control action")
    path = command_path()
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


def consume_control_command(max_age_seconds: float = 10.0) -> dict[str, object] | None:
    path = command_path()
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return None
    try:
        raw = json.loads(raw_text)
        action = str(raw.get("action", ""))
        created_at = float(raw.get("created_at", 0))
        if action not in {"show_status", "show_settings", "check_update"}:
            return None
        if created_at <= 0 or time.time() - created_at > max_age_seconds:
            return None
        return raw
    except (ValueError, TypeError):
        return None
