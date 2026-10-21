"""Local screensaver password; never a Windows account credential."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from pathlib import Path

from .storage import app_data_dir


def password_path() -> Path:
    return app_data_dir() / "rest-unlock.json"


def load_password() -> dict | None:
    try:
        record = json.loads(password_path().read_text(encoding="utf-8"))
        try:
            valid = (isinstance(record, dict) and record.get("iterations") == 200_000
                     and len(bytes.fromhex(record["salt"])) == 16
                     and len(bytes.fromhex(record["digest"])) == 32)
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("解锁密码配置损坏，请恢复 rest-unlock.json 后重启。")
        return record
    except FileNotFoundError:
        return None


def matches(record: dict | None, password: str) -> bool:
    if not record or record.get("unreadable"):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 bytes.fromhex(record["salt"]), record["iterations"])
    return hmac.compare_digest(digest.hex(), record["digest"])


def save_password(password: str, confirmation: str) -> dict:
    if not password:
        raise ValueError("请输入密码；内容不限，可使用中文、数字、符号或空格。")
    if password != confirmation:
        raise ValueError("两次输入的密码不一致。")
    salt = secrets.token_bytes(16)
    record = {"iterations": 200_000, "salt": salt.hex(),
              "digest": hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000).hex()}
    path = password_path()
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(record), encoding="utf-8")
    temp.replace(path)
    return record
