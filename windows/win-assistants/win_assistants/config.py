from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


APP_DIR_NAME = "win-assistants"


def app_data_dir() -> Path:
    base = Path(os.getenv("APPDATA") or (Path.home() / ".config"))
    target = base / APP_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


@dataclass
class ModuleConfig:
    enabled: bool = True
    command: list[str] = field(default_factory=list)
    delay_seconds: int = 0

    @classmethod
    def from_dict(cls, raw: object) -> "ModuleConfig":
        if not isinstance(raw, dict):
            return cls()
        command = raw.get("command", [])
        if not isinstance(command, list) or not all(isinstance(v, str) for v in command):
            command = []
        try:
            delay = max(0, min(120, int(raw.get("delay_seconds", 0))))
        except (TypeError, ValueError):
            delay = 0
        return cls(bool(raw.get("enabled", True)), command, delay)


@dataclass
class SmsConfig:
    server_base: str = "https://sms.ziboxiaozhushou.cn"
    channel: str = "iphone-code"
    protected_token: str = ""
    marker: str = "latest"
    interval_seconds: int = 5

    @classmethod
    def from_dict(cls, raw: object) -> "SmsConfig":
        if not isinstance(raw, dict):
            return cls()
        try:
            interval = max(5, min(30, int(raw.get("interval_seconds", 5))))
        except (TypeError, ValueError):
            interval = 5
        return cls(
            server_base=str(raw.get("server_base") or cls.server_base).rstrip("/"),
            channel=str(raw.get("channel") or cls.channel).strip("/"),
            protected_token=str(raw.get("protected_token") or ""),
            marker=str(raw.get("marker") or "latest"),
            interval_seconds=interval,
        )


@dataclass
class NumberInboxConfig:
    api_url: str = "https://assistant.ziboxiaozhushou.cn/api/number-inbox/pending"
    protected_token: str = ""
    interval_seconds: int = 15
    last_seen_id: int = 0
    reminder_times: list[str] = field(default_factory=lambda: ["09:00", "16:00"])

    @classmethod
    def from_dict(cls, raw: object) -> "NumberInboxConfig":
        if not isinstance(raw, dict):
            return cls()
        try:
            interval = max(10, min(120, int(raw.get("interval_seconds", 15))))
        except (TypeError, ValueError):
            interval = 15
        try:
            last_seen = max(0, int(raw.get("last_seen_id", 0)))
        except (TypeError, ValueError):
            last_seen = 0
        raw_times = raw.get("reminder_times", ["09:00", "16:00"])
        if not isinstance(raw_times, list):
            raw_times = ["09:00", "16:00"]
        reminder_times = []
        for value in raw_times:
            text = str(value or "").strip()
            if len(text) != 5 or text[2] != ":":
                continue
            try:
                hour, minute = (int(part) for part in text.split(":", 1))
            except ValueError:
                continue
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                normalized = f"{hour:02d}:{minute:02d}"
                if normalized not in reminder_times:
                    reminder_times.append(normalized)
            if len(reminder_times) >= 5:
                break
        return cls(
            api_url=str(raw.get("api_url") or cls.api_url).strip(),
            protected_token=str(raw.get("protected_token") or ""),
            interval_seconds=interval,
            last_seen_id=last_seen,
            reminder_times=reminder_times,
        )


@dataclass
class AppConfig:
    start_minimized: bool = False
    modules: dict[str, ModuleConfig] = field(default_factory=dict)
    sms: SmsConfig = field(default_factory=SmsConfig)
    number_inbox: NumberInboxConfig = field(default_factory=NumberInboxConfig)

    @classmethod
    def load(cls, defaults: dict[str, ModuleConfig] | None = None) -> "AppConfig":
        path = app_data_dir() / "config.json"
        base = {key: ModuleConfig(**asdict(value)) for key, value in (defaults or {}).items()}
        if not path.exists():
            return cls(modules=base)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for key, value in raw.get("modules", {}).items():
                base[key] = ModuleConfig.from_dict(value)
            return cls(bool(raw.get("start_minimized", False)), base, SmsConfig.from_dict(raw.get("sms")), NumberInboxConfig.from_dict(raw.get("number_inbox")))
        except (OSError, ValueError, TypeError):
            return cls(modules=base)

    def save(self) -> None:
        path = app_data_dir() / "config.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
