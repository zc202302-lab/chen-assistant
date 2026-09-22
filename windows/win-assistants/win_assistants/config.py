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
class AppConfig:
    start_minimized: bool = False
    modules: dict[str, ModuleConfig] = field(default_factory=dict)

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
            return cls(bool(raw.get("start_minimized", False)), base)
        except (OSError, ValueError, TypeError):
            return cls(modules=base)

    def save(self) -> None:
        path = app_data_dir() / "config.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
