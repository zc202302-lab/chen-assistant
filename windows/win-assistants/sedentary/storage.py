from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .secrets import load_windows_secret, save_windows_secret


APP_NAME = "久坐提醒"


def app_data_dir() -> Path:
    base = os.getenv("APPDATA") or str(Path.home() / ".config")
    target = Path(base) / APP_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


@dataclass
class Settings:
    work_minutes: int = 45
    break_minutes: int = 3
    rtsp_host: str = ""
    rtsp_port: int = 8554
    rtsp_path: str = "/rtsp_live1"
    rtsp_username: str = "admin"
    rtsp_password: str = ""
    sample_interval_seconds: float = 1.0
    absence_grace_seconds: float = 8.0
    presence_grace_seconds: float = 1.0
    start_with_windows: bool = False

    # Detection regions. roi is retained only to migrate older settings.
    roi: list[float] | None = None
    seat_rois: list[list[float]] | None = None

    @classmethod
    def load(cls) -> "Settings":
        path = app_data_dir() / "settings.json"
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            allowed = cls.__dataclass_fields__.keys()
            settings = cls(**{key: value for key, value in raw.items() if key in allowed})
            settings.rtsp_password = load_windows_secret(app_data_dir() / "rtsp-password.bin")
            if not _valid_roi(settings.roi):
                settings.roi = None
            if not isinstance(settings.seat_rois, list):
                settings.seat_rois = None
            else:
                settings.seat_rois = [roi for roi in settings.seat_rois if _valid_roi(roi)]
                if not settings.seat_rois:
                    settings.seat_rois = None
            if not settings.seat_rois and settings.roi:
                settings.seat_rois = [list(settings.roi)]
            return settings
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        path = app_data_dir() / "settings.json"
        temp = path.with_suffix(".tmp")
        values = asdict(self)
        values.pop("rtsp_password", None)
        temp.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
        save_windows_secret(app_data_dir() / "rtsp-password.bin", self.rtsp_password)


def _valid_roi(roi: object) -> bool:
    if not isinstance(roi, list) or len(roi) != 4:
        return False
    try:
        x, y, w, h = [float(v) for v in roi]
    except (TypeError, ValueError):
        return False
    return 0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1 and x + w <= 1.001 and y + h <= 1.001


def log_event(event: str, duration_seconds: float = 0.0) -> None:
    path = app_data_dir() / "events.csv"
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(["时间", "事件", "持续秒数"])
        writer.writerow([
            datetime.now().isoformat(timespec="seconds"),
            event,
            int(max(0, duration_seconds)),
        ])


@dataclass
class DailyStats:
    date: str
    seated_seconds: float = 0.0
    away_seconds: float = 0.0
    reminder_count: int = 0
    completed_break_count: int = 0
    current_seated_streak: float = 0.0
    longest_seated_streak: float = 0.0

    @classmethod
    def load_today(cls) -> "DailyStats":
        today = datetime.now().date().isoformat()
        path = app_data_dir() / "daily-stats.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if raw.get("date") == today:
                return cls(**{k: raw[k] for k in cls.__dataclass_fields__ if k in raw})
        except (OSError, ValueError, TypeError):
            pass
        return cls(date=today)

    def add_sample(self, present: bool, elapsed: float) -> None:
        elapsed = max(0.0, min(float(elapsed), 10.0))
        if present:
            self.seated_seconds += elapsed
            self.current_seated_streak += elapsed
            self.longest_seated_streak = max(self.longest_seated_streak, self.current_seated_streak)
        else:
            self.away_seconds += elapsed
            self.current_seated_streak = 0.0

    def save(self) -> None:
        path = app_data_dir() / "daily-stats.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
