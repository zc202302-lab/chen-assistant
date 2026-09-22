from __future__ import annotations

import base64
import ctypes
import json
import os
import queue
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig, SmsConfig


CODE_PATTERNS = (
    re.compile(r"(?:验证码|校验码|动态码|确认码|verification\s*code|security\s*code|otp)[^0-9]{0,16}([0-9]{4,8})", re.IGNORECASE),
    re.compile(r"(?<!\d)([0-9]{4,8})(?!\d)"),
)


def find_code(text: str) -> str | None:
    for pattern in CODE_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return match.group(1)
    return None


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes) -> tuple[_DataBlob, object]:
    buffer = ctypes.create_string_buffer(data)
    value = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return value, buffer


def _local_free(pointer: object) -> None:
    local_free = ctypes.windll.kernel32.LocalFree
    local_free.argtypes = (ctypes.c_void_p,)
    local_free.restype = ctypes.c_void_p
    local_free(pointer)


def protect_secret(value: str) -> str:
    if not value:
        return ""
    raw = value.encode("utf-8")
    if sys.platform != "win32":
        return "portable:" + base64.b64encode(raw).decode("ascii")
    source, source_buffer = _blob(raw)
    result = _DataBlob()
    crypt = ctypes.windll.crypt32.CryptProtectData
    crypt.argtypes = (
        ctypes.POINTER(_DataBlob), ctypes.c_wchar_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_DataBlob),
    )
    crypt.restype = ctypes.c_bool
    if not crypt(ctypes.byref(source), "win-assistants SMS token", None, None, None, 0, ctypes.byref(result)):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(result.pbData, result.cbData)
        return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
    finally:
        _local_free(result.pbData)
        del source_buffer


def unprotect_secret(value: str) -> str:
    if not value:
        return ""
    if value.startswith("portable:") and sys.platform != "win32":
        return base64.b64decode(value[9:]).decode("utf-8")
    if not value.startswith("dpapi:") or sys.platform != "win32":
        return ""
    encrypted = base64.b64decode(value[6:])
    source, source_buffer = _blob(encrypted)
    result = _DataBlob()
    crypt = ctypes.windll.crypt32.CryptUnprotectData
    crypt.argtypes = (
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_DataBlob),
    )
    crypt.restype = ctypes.c_bool
    if not crypt(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result.pbData, result.cbData).decode("utf-8")
    finally:
        _local_free(result.pbData)
        del source_buffer


def _decrypt_legacy_token(cipher: str) -> str:
    if not cipher or sys.platform != "win32":
        return ""
    script = (
        "$c=[Console]::In.ReadToEnd().Trim();"
        "$s=ConvertTo-SecureString -String $c;"
        "$p=New-Object System.Management.Automation.PSCredential('ntfy',$s);"
        "[Console]::Out.Write($p.GetNetworkCredential().Password)"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            input=cipher,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def migrate_legacy_config(config: AppConfig) -> bool:
    if config.sms.protected_token:
        return False
    base = Path(os.getenv("APPDATA") or "")
    path = base / "iPhoneSmsBridgeNoServer" / "config.json"
    if not path.exists():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        token = _decrypt_legacy_token(str(raw.get("token") or ""))
        config.sms = SmsConfig(
            server_base=str(raw.get("serverBase") or config.sms.server_base).rstrip("/"),
            channel=str(raw.get("channel") or config.sms.channel).strip("/"),
            protected_token=protect_secret(token) if token else "",
            marker=str(raw.get("marker") or "latest"),
            interval_seconds=max(5, min(30, int(raw.get("interval") or 5))),
        )
        config.save()
        return True
    except (OSError, ValueError, TypeError):
        return False


@dataclass(frozen=True)
class SmsEvent:
    kind: str
    message: str
    code: str = ""
    marker: str = ""


class SmsReceiver:
    def __init__(self) -> None:
        self.events: queue.Queue[SmsEvent] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._response = None
        self._lock = threading.Lock()
        self._generation = 0

    def start(self, settings: SmsConfig, token: str) -> None:
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
            name="sms-receiver",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        stop_event = self._stop
        stop_event.set()
        self._generation += 1
        with self._lock:
            response = self._response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(2)
        self._thread = None

    @staticmethod
    def build_url(settings: SmsConfig) -> str:
        channel = urllib.parse.quote(settings.channel, safe="")
        marker = urllib.parse.quote(settings.marker or "latest", safe="")
        return f"{settings.server_base.rstrip('/')}/{channel}/json?since={marker}"

    def _is_current(self, generation: int) -> bool:
        return generation == self._generation

    def _run(self, settings: SmsConfig, token: str, stop_event: threading.Event, generation: int) -> None:
        if not settings.server_base or not settings.channel or not token:
            if self._is_current(generation):
                self.events.put(SmsEvent("config", "请先完成短信助手设置"))
            return
        wait_seconds = max(5, min(30, settings.interval_seconds))
        while not stop_event.is_set() and self._is_current(generation):
            request = urllib.request.Request(
                self.build_url(settings),
                headers={"Authorization": f"Bearer {token}", "User-Agent": "win-assistants/0.2"},
            )
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    if stop_event.is_set() or not self._is_current(generation):
                        return
                    with self._lock:
                        self._response = response
                    for raw_line in response:
                        if stop_event.is_set() or not self._is_current(generation):
                            return
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if line:
                            self._handle_line(line, settings, generation)
            except urllib.error.HTTPError as exc:
                if not self._is_current(generation):
                    return
                if exc.code in (401, 403):
                    self.events.put(SmsEvent("auth", "身份验证失败，请检查访问令牌和主题权限"))
                    wait_seconds = 15
                elif exc.code == 429:
                    self.events.put(SmsEvent("rate", "请求过于频繁，30 秒后自动重试"))
                    wait_seconds = 30
                elif not stop_event.is_set():
                    self.events.put(SmsEvent("error", f"连接失败：HTTP {exc.code}"))
            except (OSError, ValueError) as exc:
                if not stop_event.is_set() and self._is_current(generation):
                    self.events.put(SmsEvent("error", f"连接失败：{exc}"))
            finally:
                with self._lock:
                    if self._is_current(generation):
                        self._response = None
            stop_event.wait(wait_seconds)

    def _handle_line(self, line: str, settings: SmsConfig, generation: int | None = None) -> None:
        if generation is not None and not self._is_current(generation):
            return
        try:
            message = json.loads(line)
        except ValueError:
            return
        event = message.get("event")
        if event == "open":
            self.events.put(SmsEvent("connected", "已连接，等待新验证码"))
            return
        if event != "message":
            return
        text = str(message.get("message") or "")
        code = find_code(text) or ""
        marker = str(message.get("id") or "")
        status = "收到新验证码" if code else "收到新短信，但未识别出验证码"
        self.events.put(SmsEvent("message", status, code, marker))

    def publish_test(self, settings: SmsConfig, token: str) -> None:
        def worker() -> None:
            url = f"{settings.server_base.rstrip('/')}/{urllib.parse.quote(settings.channel, safe='')}"
            request = urllib.request.Request(
                url,
                data="测试验证码 482731".encode("utf-8"),
                method="POST",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain; charset=utf-8"},
            )
            try:
                with urllib.request.urlopen(request, timeout=15):
                    self.events.put(SmsEvent("test", "测试短信已发送，请等待接收"))
            except Exception as exc:
                self.events.put(SmsEvent("error", f"测试发送失败：{exc}"))

        threading.Thread(target=worker, name="sms-test", daemon=True).start()
