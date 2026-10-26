from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlparse, urlsplit


PORT = 18763
HELPER_COMPAT_VERSION = "0.9"
ALLOWED_ROOT_DOMAIN = "ziboxiaozhushou.cn"
MAX_BODY_BYTES = 12_000_000
INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def is_allowed_origin(origin: str) -> bool:
    if not origin or not origin.strip():
        return False
    try:
        parsed = urlparse(origin)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https"):
            return False
        if host in ("127.0.0.1", "localhost"):
            return True
        return host == ALLOWED_ROOT_DOMAIN or host.endswith("." + ALLOWED_ROOT_DOMAIN)
    except ValueError:
        return False


def decode_b64_text(value: object) -> str:
    if not value:
        return ""
    return base64.b64decode(str(value), validate=True).decode("utf-8")


def safe_attachment_name(name: str) -> str:
    value = INVALID_FILENAME.sub("_", name or "payment.txt")
    return value[:120]


def validate_compose_payload(payload: object) -> tuple[str, str, str, str, bytes, str]:
    if not isinstance(payload, dict):
        raise ValueError("invalid compose payload")
    for name in ("subject_b64", "attachment_filename_b64", "attachment_content_base64", "attachment_sha256"):
        if not payload.get(name):
            raise ValueError(f"missing {name}")
    recipient = decode_b64_text(payload.get("recipient_b64"))
    subject = decode_b64_text(payload["subject_b64"])
    body = decode_b64_text(payload.get("body_b64"))
    requested_name = decode_b64_text(payload["attachment_filename_b64"])
    if not requested_name or safe_attachment_name(requested_name) != requested_name:
        raise ValueError("TXT attachment filename changed during local safety normalization")
    try:
        content = base64.b64decode(str(payload["attachment_content_base64"]), validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid TXT attachment base64") from exc
    if not content:
        raise ValueError("TXT attachment payload is empty")
    expected = str(payload["attachment_sha256"]).strip().lower()
    if not SHA256_PATTERN.fullmatch(expected):
        raise ValueError("invalid TXT attachment SHA256")
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise ValueError("TXT attachment payload SHA256 mismatch")
    return recipient, subject, body, requested_name, content, expected


def build_mailto_uri(recipient: str, subject: str, body: str) -> str:
    parts: list[str] = []
    if subject:
        parts.append("subject=" + quote(subject, safe=""))
    if body:
        html_body = body.replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")
        parts.append("body=" + quote(html_body, safe=""))
    target = "mailto:" + quote(recipient, safe="")
    return target if not parts else target + "?" + "&".join(parts)


def _find_foxmail_exe() -> Path | None:
    if sys.platform != "win32":
        return None
    import winreg

    flags = (getattr(winreg, "KEY_WOW64_32KEY", 0), getattr(winreg, "KEY_WOW64_64KEY", 0))
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for flag in flags:
            try:
                with winreg.OpenKey(
                    hive,
                    r"SOFTWARE\Clients\Mail\Foxmail\shell\open\command",
                    0,
                    winreg.KEY_READ | flag,
                ) as key:
                    command = os.path.expandvars(str(winreg.QueryValueEx(key, "")[0]))
                match = re.match(r'^\s*"([^"]+Foxmail\.exe)"|^\s*([^\s]+Foxmail\.exe)', command, re.I)
                if match:
                    path = Path(match.group(1) or match.group(2))
                    if path.is_file():
                        return path
            except OSError:
                pass
    candidates = (
        Path(os.getenv("ProgramFiles", "")) / "Foxmail 7.2" / "Foxmail.exe",
        Path(os.getenv("ProgramFiles(x86)", "")) / "Foxmail 7.2" / "Foxmail.exe",
        Path(os.getenv("LOCALAPPDATA", "")) / "Foxmail 7.2" / "Foxmail.exe",
    )
    return next((path for path in candidates if path.is_file()), None)


def _foxmail_process_ids() -> set[int]:
    if sys.platform != "win32":
        return set()

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return set()
    result: set[int] = set()
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == "foxmail.exe":
                result.add(int(entry.th32ProcessID))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return result


def _foxmail_windows() -> dict[int, str]:
    if sys.platform != "win32":
        return {}
    process_ids = _foxmail_process_ids()
    result: dict[int, str] = {}
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(handle, _parameter):
        if not user32.IsWindowVisible(handle):
            return True
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
        if int(process_id.value) not in process_ids:
            return True
        length = user32.GetWindowTextLengthW(handle)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, len(buffer))
        result[int(handle)] = buffer.value
        return True

    user32.EnumWindows(callback, 0)
    return result


def _wait_for_compose_window(before: set[int], subject: str, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.2)
        windows = _foxmail_windows()
        if any(handle not in before for handle in windows):
            return True
        if subject and any(subject.casefold() in title.casefold() for title in windows.values()):
            return True
    return False


def _set_file_drop_clipboard(path: Path) -> bool:
    if sys.platform != "win32" or not path.is_file():
        return False
    user32, kernel32, shell32 = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.shell32
    user32.OpenClipboard.argtypes = (wintypes.HWND,)
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardData.argtypes = (wintypes.UINT,)
    user32.GetClipboardData.restype = wintypes.HANDLE
    encoded = (str(path) + "\0\0").encode("utf-16-le")
    payload = struct.pack("<IiiII", 20, 0, 0, 0, 1) + encoded
    for _attempt in range(8):
        handle = None
        if not user32.OpenClipboard(None):
            time.sleep(0.18)
            continue
        try:
            if not user32.EmptyClipboard():
                continue
            kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
            kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
            kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
            kernel32.GlobalLock.restype = wintypes.LPVOID
            kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
            kernel32.GlobalFree.argtypes = (wintypes.HGLOBAL,)
            kernel32.GlobalFree.restype = wintypes.HGLOBAL
            handle = kernel32.GlobalAlloc(0x0002, len(payload))
            if not handle:
                continue
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                continue
            ctypes.memmove(pointer, payload, len(payload))
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(15, handle):
                continue
            handle = None  # Clipboard owns the allocation after SetClipboardData succeeds.
            # Explorer-compatible Cut semantics; CF_HDROP remains the file payload.
            user32.RegisterClipboardFormatW.argtypes = (wintypes.LPCWSTR,)
            user32.RegisterClipboardFormatW.restype = wintypes.UINT
            effect_format = user32.RegisterClipboardFormatW("Preferred DropEffect")
            handle = kernel32.GlobalAlloc(0x0002, 4)
            if not effect_format or not handle:
                continue
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                continue
            ctypes.memmove(pointer, struct.pack("<I", 2), 4)
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(effect_format, handle):
                continue
            handle = None
            clipboard_handle = user32.GetClipboardData(15)
            shell32.DragQueryFileW.argtypes = (wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT)
            shell32.DragQueryFileW.restype = wintypes.UINT
            count = shell32.DragQueryFileW(clipboard_handle, 0xFFFFFFFF, None, 0)
            for index in range(count):
                length = shell32.DragQueryFileW(clipboard_handle, index, None, 0)
                buffer = ctypes.create_unicode_buffer(length + 1)
                shell32.DragQueryFileW(clipboard_handle, index, buffer, len(buffer))
                if Path(buffer.value) == path:
                    return True
        finally:
            if handle:
                kernel32.GlobalFree(handle)
            user32.CloseClipboard()
        time.sleep(0.18)
    return False


_compose_lock = threading.Lock()


def payment_attachment_directory() -> Path:
    from .config import app_data_dir
    root = app_data_dir() / "PaymentTXT"
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise RuntimeError("TXT directory must not be a symbolic link")
    return root


def prepare_payment_attachment(filename: str, content: bytes, expected_hash: str) -> Path:
    if Path(filename).suffix.lower() != ".txt" or safe_attachment_name(filename) != filename:
        raise ValueError("TXT attachment filename invalid")
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise ValueError("TXT attachment SHA256 mismatch")
    root = payment_attachment_directory()
    # Only this dedicated directory is managed; unrelated downloads are untouched.
    descriptor, staged_name = tempfile.mkstemp(prefix=".payment-", suffix=".next", dir=root)
    staged = Path(staged_name)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
    try:
        if hashlib.sha256(staged.read_bytes()).hexdigest() != expected_hash:
            raise RuntimeError("TXT attachment file SHA256 mismatch after write")
        for previous in root.iterdir():
            if previous.suffix.lower() == ".txt" and (previous.is_file() or previous.is_symlink()):
                previous.unlink()
        attachment = root / filename
        staged.replace(attachment)
        return attachment
    finally:
        staged.unlink(missing_ok=True)


def compose_foxmail_draft(payload: object) -> dict[str, object]:
    if not _compose_lock.acquire(blocking=False):
        raise RuntimeError("TXT preparation already in progress; retry shortly")
    try:
        return _compose_foxmail_draft(payload)
    finally:
        _compose_lock.release()


def _compose_foxmail_draft(payload: object) -> dict[str, object]:
    if sys.platform != "win32":
        raise RuntimeError("Foxmail bridge only supports Windows")
    recipient, subject, body, filename, content, expected_hash = validate_compose_payload(payload)
    foxmail = _find_foxmail_exe()
    if foxmail is None:
        raise RuntimeError("Foxmail.exe was not found")
    attachment = prepare_payment_attachment(filename, content, expected_hash)
    before = set(_foxmail_windows())
    subprocess.Popen([str(foxmail), build_mailto_uri(recipient, subject, body)], close_fds=True)
    if not _wait_for_compose_window(before, subject):
        raise RuntimeError("Foxmail compose window did not appear after direct Foxmail.exe mailto launch")
    if not _set_file_drop_clipboard(attachment):
        raise RuntimeError("TXT file clipboard verification failed")
    return {
        "ok": True,
        "version": HELPER_COMPAT_VERSION,
        "mode": "foxmail-exe-mailto-clipboard-ready",
        "state": "draft-open-clipboard-ready",
        "verified": True,
        "launch_verified": True,
        "attachment_file_verified": True,
        "attachment_clipboard_verified": True,
        "attachment_integrity_verified": True,
        "explorer_dispatched": False,
        "attachment_filename_exact": True,
    }


def _health_payload() -> dict[str, object]:
    return {
        "ok": True,
        "name": "win-assistants Foxmail Bridge",
        "version": HELPER_COMPAT_VERSION,
        "compose": True,
        "verified_compose": True,
        "launch_mode": "foxmail-exe-mailto-clipboard-ready",
        "attachment_mode": "clipboard-file-drop",
        "auto_send": False,
        "mapi_required": False,
    }


class _BridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class FoxmailBridge:
    def __init__(self, port: int = PORT, composer: Callable[[object], dict[str, object]] | None = None) -> None:
        self.port = port
        self.composer = composer or compose_foxmail_draft
        self._server: _BridgeServer | None = None
        self._thread: threading.Thread | None = None
        self._compose_lock = threading.Lock()
        self.external_compatible = False

    def _handler(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def _reply(self, status: int, payload: dict[str, object] | None, origin: str = "") -> None:
                body = b"" if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                if origin:
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type")
                    self.send_header("Access-Control-Allow-Private-Network", "true")
                    self.send_header("Vary", "Origin")
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _origin(self) -> str | None:
                origin = self.headers.get("Origin", "")
                if not is_allowed_origin(origin):
                    self._reply(403, {"ok": False, "error": "origin denied"})
                    return None
                return origin

            def do_OPTIONS(self):
                origin = self._origin()
                if origin is not None:
                    self._reply(204, None, origin)

            def do_GET(self):
                origin = self._origin()
                if origin is None:
                    return
                if urlsplit(self.path).path == "/health":
                    self._reply(200, _health_payload(), origin)
                else:
                    self._reply(404, {"ok": False, "error": "not found"}, origin)

            def do_POST(self):
                origin = self._origin()
                if origin is None:
                    return
                if urlsplit(self.path).path != "/compose":
                    self._reply(404, {"ok": False, "error": "not found"}, origin)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._reply(400, {"ok": False, "error": "bad request"}, origin)
                    return
                if length <= 0 or length > MAX_BODY_BYTES:
                    status = 413 if length > MAX_BODY_BYTES else 400
                    self._reply(status, {"ok": False, "error": "payload too large" if status == 413 else "bad request"}, origin)
                    return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    with bridge._compose_lock:
                        result = bridge.composer(payload)
                    self._reply(200, result, origin)
                except Exception as exc:
                    self._reply(500, {"ok": False, "error": str(exc), "version": HELPER_COMPAT_VERSION}, origin)

        return Handler

    def start(self) -> tuple[bool, str]:
        if self._thread is not None and self._thread.is_alive():
            return True, "运行中（内置）"
        try:
            self._server = _BridgeServer(("127.0.0.1", self.port), self._handler())
        except OSError:
            if self._probe_compatible():
                self.external_compatible = True
                return True, "兼容独立版正在运行"
            return False, f"本机端口 {self.port} 被其他程序占用"
        self.port = int(self._server.server_address[1])
        self.external_compatible = False
        self._cleanup_old_files()
        self._thread = threading.Thread(target=self._server.serve_forever, name="foxmail-bridge", daemon=True)
        self._thread.start()
        return True, "运行中（内置）"

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        self.external_compatible = False
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(2)

    def _probe_compatible(self) -> bool:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/health",
            headers={"Origin": "http://localhost"},
        )
        try:
            with urllib.request.urlopen(request, timeout=1) as response:
                data = json.loads(response.read().decode("utf-8"))
            return bool(
                data.get("ok")
                and data.get("version") == HELPER_COMPAT_VERSION
                and data.get("launch_mode") == "foxmail-exe-mailto-clipboard-ready"
                and data.get("attachment_mode") == "clipboard-file-drop"
                and data.get("auto_send") is False
            )
        except Exception:
            return False

    @staticmethod
    def _cleanup_old_files() -> None:
        root = Path(tempfile.gettempdir()) / "ChenAssistantPaymentClipboard"
        root.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - 7200
        for child in root.iterdir():
            try:
                if child.is_dir() and child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                pass
