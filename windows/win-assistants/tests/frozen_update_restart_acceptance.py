"""Run the shipped PE and real Windows PowerShell through replace and rollback."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def gui_pid(executable: Path) -> int | None:
    user = ctypes.windll.user32
    user.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    user.FindWindowW.restype = wintypes.HWND
    window = user.FindWindowW(None, "晨的小助手 · Windows")
    if not window:
        return None
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user.GetWindowThreadProcessId(window, ctypes.byref(pid))
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    handle = kernel.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        kernel.QueryFullProcessImageNameW.argtypes = (
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
            return None
        return pid.value if Path(buffer.value).resolve() == executable.resolve() else None
    finally:
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle(handle)


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


def run_case(binary: bytes, directory: Path, rollback: bool) -> None:
    directory.mkdir(parents=True)
    executable = directory / "win-assistants.exe"
    executable.write_bytes(binary)
    (directory / "acceptance-case").touch()
    env = os.environ.copy()
    env["APPDATA"] = str(directory / "roaming")
    env["LOCALAPPDATA"] = str(directory / "local")
    command = [str(executable), "--update-restart-self-test", str(directory)]
    if rollback:
        command.append("--test-rollback")
    parent = subprocess.Popen(command, env=env)
    new_pid = None
    log = directory / "local" / "win-assistants" / "update.log"
    try:
        assert parent.wait(timeout=120) == 0, "Frozen updater parent failed"
        deadline = time.monotonic() + 150
        text = ""
        while time.monotonic() < deadline:
            if log.exists():
                text = log.read_text(encoding="utf-8-sig")
            new_pid = gui_pid(executable)
            expected = "rolled back to previous executable" if rollback else "startup confirmed"
            old_file = directory / "old-meipass.txt"
            old_gone = old_file.exists() and not Path(old_file.read_text(encoding="utf-8")).exists()
            if expected in text and new_pid and old_gone:
                break
            time.sleep(0.5)
        else:
            raise AssertionError("No live restarted GUI after old runtime cleanup:\n" + text)
        assert hashlib.sha256(executable.read_bytes()).digest() == hashlib.sha256(binary).digest()
        assert "candidate sha256 mismatch" not in text
        assert "ROLLBACK FAILED" not in text
        if rollback:
            assert "new executable did not confirm startup" in text
            assert "previous restart requested" in text
        else:
            assert "FAILED:" not in text
            assert not executable.with_name(executable.name + ".previous").exists()
        print(("ROLLBACK" if rollback else "RESTART"), "VERIFIED: real GUI alive, old _MEI removed", flush=True)
    finally:
        if new_pid:
            kill_tree(new_pid)
        kill_tree(parent.pid)
        # Kill only the PIDs belonging to this test case recorded by the helper.
        if log.exists():
            import re
            for value in re.findall(r"(?:restart requested|startup confirmed) pid=(\d+)",
                                    log.read_text(encoding="utf-8-sig")):
            kill_tree(int(value))


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("This acceptance requires real Windows")
    binary = Path(sys.argv[1]).read_bytes()
    with tempfile.TemporaryDirectory(prefix="win-update-") as temp:
        root = Path(temp) / "更新 ' 路径"
        run_case(binary, root / "success", False)
        run_case(binary, root / "rollback", True)
