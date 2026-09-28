from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass

STATUS_URL = "https://assistant.ziboxiaozhushou.cn/number-submit/status/pending-count"


@dataclass(frozen=True)
class NumberInboxEvent:
    kind: str
    pending_count: int
    message: str


def fetch_pending_count(timeout: float = 8.0) -> int:
    request = urllib.request.Request(
        STATUS_URL + "?t=" + str(int(time.time())),
        headers={"User-Agent": "win-assistants-number-inbox/1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(16 * 1024)
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("pending_count"), int):
        raise RuntimeError("号码收集状态格式无效")
    return max(0, int(payload["pending_count"]))


def _escape_ps(value: str) -> str:
    return value.replace("'", "''")


def show_windows_notification(title: str, message: str) -> None:
    script = """$ErrorActionPreference='SilentlyContinue'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text>{title}</text><text>{message}</text></binding></visual></toast>')
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('win-assistants').Show($toast)
""".format(title=_escape_ps(title), message=_escape_ps(message))
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )


class NumberInboxWatcher:
    def __init__(self, interval_seconds: int = 15) -> None:
        self.interval_seconds = max(10, int(interval_seconds))
        self.events: queue.Queue[NumberInboxEvent] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_count: int | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="number-inbox-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                count = fetch_pending_count()
                previous = self._last_count
                self._last_count = count
                self.events.put(NumberInboxEvent("status", count, f"待处理号码 {count} 个"))
                if previous is not None and count > previous:
                    added = count - previous
                    show_windows_notification(
                        "晨的小助手 · 新号码",
                        f"新增 {added} 个待处理号码，目前共 {count} 个。",
                    )
                    self.events.put(NumberInboxEvent("new", count, f"新增 {added} 个号码"))
            except Exception as exc:
                self.events.put(NumberInboxEvent("error", self._last_count or 0, f"号码提醒暂时离线：{exc}"))
            self._stop.wait(self.interval_seconds)
