from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

UPDATE_MANIFEST_URL = "https://assistant.ziboxiaozhushou.cn/static/win-assistants/update.json"


def _version_tuple(value: str) -> tuple[int, ...]:
    text = (value or "").strip().lower()
    if text.startswith("v"):
        text = text[1:]
    parts = []
    for chunk in text.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts or [0])


def fetch_manifest(timeout: float = 12.0) -> dict[str, object]:
    request = urllib.request.Request(
        UPDATE_MANIFEST_URL + "?t=" + str(os.getpid()),
        headers={"User-Agent": "win-assistants-updater/1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(256 * 1024)
    manifest = json.loads(data.decode("utf-8"))
    required = ("version", "exe_url", "sha256")
    if not isinstance(manifest, dict) or any(not manifest.get(k) for k in required):
        raise RuntimeError("更新清单格式无效")
    digest = str(manifest["sha256"]).strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise RuntimeError("更新清单 SHA-256 无效")
    return manifest


def newer_version_available(current_version: str, manifest: dict[str, object]) -> bool:
    return _version_tuple(str(manifest.get("version", "0"))) > _version_tuple(current_version)


def _download_file(url: str, target: Path, timeout: float = 60.0) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "win-assistants-updater/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response, target.open("wb") as handle:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            handle.write(block)


def stage_update(manifest: dict[str, object]) -> Path:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("当前不是已打包 EXE，不能执行自更新")
    update_root = Path(os.getenv("LOCALAPPDATA") or tempfile.gettempdir()) / "win-assistants" / "updates"
    update_root.mkdir(parents=True, exist_ok=True)
    version = str(manifest["version"]).strip().replace("/", "_").replace("\\", "_")
    staged = update_root / f"win-assistants-{version}.exe"
    temp = staged.with_suffix(".download")
    try:
        temp.unlink(missing_ok=True)
        _download_file(str(manifest["exe_url"]), temp)
        expected_size = int(manifest.get("size", 0) or 0)
        if expected_size and temp.stat().st_size != expected_size:
            raise RuntimeError("更新文件大小校验失败")
        digest = hashlib.sha256(temp.read_bytes()).hexdigest()
        if digest != str(manifest["sha256"]).strip().lower():
            raise RuntimeError("更新文件 SHA-256 校验失败")
        with temp.open("rb") as handle:
            if handle.read(2) != b"MZ":
                raise RuntimeError("更新文件不是有效 Windows EXE")
        temp.replace(staged)
        return staged
    finally:
        temp.unlink(missing_ok=True)


def launch_replacement(staged: Path) -> None:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("当前不是已打包 EXE，不能替换程序")
    target = Path(sys.executable).resolve()
    if not staged.is_file():
        raise RuntimeError("待安装更新文件不存在")

    script = staged.parent / "apply-update.cmd"
    body = (
        "@echo off\r\n"
        "setlocal\r\n"
        f"set \"OLDPID={os.getpid()}\"\r\n"
        f"set \"SOURCE={staged}\"\r\n"
        f"set \"TARGET={target}\"\r\n"
        ":waitloop\r\n"
        "tasklist /FI \"PID eq %OLDPID%\" 2>NUL | findstr /R /C:\"[ ]%OLDPID%[ ]\" >NUL\r\n"
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >NUL\r\n"
        "  goto waitloop\r\n"
        ")\r\n"
        "copy /Y \"%SOURCE%\" \"%TARGET%\" >NUL\r\n"
        "if errorlevel 1 exit /b 1\r\n"
        "start \"\" \"%TARGET%\" --background\r\n"
        "del /Q \"%SOURCE%\" >NUL 2>&1\r\n"
        "del /Q \"%~f0\" >NUL 2>&1\r\n"
    )
    script.write_text(body, encoding="ascii", errors="strict")
    subprocess.Popen(
        ["cmd.exe", "/c", str(script)],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )
