from __future__ import annotations

import json
import queue
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import NumberInboxConfig


@dataclass(frozen=True)
class NumberInboxEvent:
    kind: str
    message: str
    pending_count: int = 0
    item_id: int = 0
    number: str = ""
    submitter: str = ""
    note: str = ""
    pending_ids: tuple[int, ...] | None = None


class NumberInboxReceiver:
    def __init__(self) -> None:
        self.events: queue.Queue[NumberInboxEvent] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._generation = 0

    def start(self, settings: NumberInboxConfig, token: str) -> None:
        self.stop()
        self._stop = threading.Event()
        self._generation += 1
        generation = self._generation
        while True:
            try:
                self.events.get_nowait()
            except queue.Empty:
                break
        self._thread = threading.Thread(
            target=self._run,
            args=(settings, token, self._stop, generation),
            name="number-inbox-receiver",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._generation += 1
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(2)
        self._thread = None

    def _is_current(self, generation: int) -> bool:
        return generation == self._generation

    @staticmethod
    def fetch(settings: NumberInboxConfig, token: str, timeout: float = 15.0) -> dict[str, object]:
        if not settings.api_url or not token:
            raise ValueError("请先完成号码提醒设置")
        request = urllib.request.Request(
            settings.api_url,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "win-assistants-number-inbox/1",
                "Cache-Control": "no-cache",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(256 * 1024)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RuntimeError("号码提醒接口返回无效")
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise RuntimeError("号码提醒接口 items 无效")
        return payload

    @staticmethod
    def complete(settings: NumberInboxConfig, token: str, item_id: int, timeout: float = 15.0) -> dict[str, object]:
        if not settings.api_url or not token:
            raise ValueError("请先完成号码提醒设置")
        base = settings.api_url.rsplit("/pending", 1)[0]
        if base == settings.api_url:
            raise ValueError("号码提醒接口地址无效")
        request = urllib.request.Request(
            f"{base}/{int(item_id)}/done",
            data=b"",
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "win-assistants-number-inbox/1",
                "Cache-Control": "no-cache",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(256 * 1024)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("ok") is not True or payload.get("status") != "done":
            raise RuntimeError("号码完成接口返回无效")
        return payload

    def _run(
        self,
        settings: NumberInboxConfig,
        token: str,
        stop_event: threading.Event,
        generation: int,
    ) -> None:
        if not settings.api_url or not token:
            if self._is_current(generation):
                self.events.put(NumberInboxEvent("config", "请先完成号码提醒设置"))
            return

        interval = max(10, min(120, int(settings.interval_seconds)))
        primed = settings.last_seen_id > 0
        last_seen = max(0, int(settings.last_seen_id))

        while not stop_event.is_set() and self._is_current(generation):
            try:
                payload = self.fetch(settings, token)
                pending_count = max(0, int(payload.get("pending_count", 0) or 0))
                latest_id = max(0, int(payload.get("latest_id", 0) or 0))
                items = payload.get("items", [])
                pending_ids_raw = payload.get("pending_ids")
                pending_ids = None
                if isinstance(pending_ids_raw, list):
                    normalized_ids = []
                    for value in pending_ids_raw:
                        try:
                            normalized_ids.append(int(value))
                        except (TypeError, ValueError):
                            continue
                    pending_ids = tuple(normalized_ids)

                if not primed:
                    last_seen = latest_id
                    primed = True
                    self.events.put(
                        NumberInboxEvent(
                            "connected",
                            f"已连接 · {pending_count} 个待录入",
                            pending_count=pending_count,
                            item_id=last_seen,
                            pending_ids=pending_ids,
                        )
                    )
                    for item in reversed(items):
                        if not isinstance(item, dict):
                            continue
                        try:
                            item_id = int(item.get("id", 0) or 0)
                        except (TypeError, ValueError):
                            continue
                        if item_id <= 0:
                            continue
                        self.events.put(
                            NumberInboxEvent(
                                "snapshot",
                                "同步现有待处理号码",
                                pending_count=pending_count,
                                item_id=item_id,
                                number=str(item.get("number") or ""),
                                submitter=str(item.get("submitter") or ""),
                                note=str(item.get("note") or ""),
                                pending_ids=pending_ids,
                            )
                        )
                else:
                    unseen = []
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        try:
                            item_id = int(item.get("id", 0) or 0)
                        except (TypeError, ValueError):
                            continue
                        if item_id > last_seen:
                            unseen.append((item_id, item))
                    unseen.sort(key=lambda pair: pair[0])
                    for item_id, item in unseen:
                        self.events.put(
                            NumberInboxEvent(
                                "new",
                                "收到新的待录入号码",
                                pending_count=pending_count,
                                item_id=item_id,
                                number=str(item.get("number") or ""),
                                submitter=str(item.get("submitter") or ""),
                                note=str(item.get("note") or ""),
                                pending_ids=pending_ids,
                            )
                        )
                    last_seen = max(last_seen, latest_id)
                    if not unseen:
                        self.events.put(
                            NumberInboxEvent(
                                "status",
                                f"已连接 · {pending_count} 个待录入",
                                pending_count=pending_count,
                                item_id=last_seen,
                                pending_ids=pending_ids,
                            )
                        )
            except urllib.error.HTTPError as exc:
                if not self._is_current(generation):
                    return
                if exc.code in (401, 403):
                    self.events.put(NumberInboxEvent("auth", "连接码无效，请重新设置"))
                else:
                    self.events.put(NumberInboxEvent("error", f"连接失败：HTTP {exc.code}"))
            except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
                if not stop_event.is_set() and self._is_current(generation):
                    self.events.put(NumberInboxEvent("error", f"连接失败：{exc}"))

            stop_event.wait(interval)
