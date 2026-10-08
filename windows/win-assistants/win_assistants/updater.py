from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

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


def _cache_busted_url(url: str, *, version: str = "", sha256: str = "") -> str:
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query.extend(
        [
            ("version", version or "unknown"),
            ("sha", (sha256 or "none")[:16]),
            ("nocache", str(time.time_ns())),
        ]
    )
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment)
    )


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": "win-assistants-updater/2",
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


def fetch_manifest(timeout: float = 12.0) -> dict[str, object]:
    url = _cache_busted_url(UPDATE_MANIFEST_URL)
    with urllib.request.urlopen(_request(url), timeout=timeout) as response:
        data = response.read(256 * 1024)
    manifest = json.loads(data.decode("utf-8"))
    required = ("version", "exe_url", "sha256", "size")
    if not isinstance(manifest, dict) or any(not manifest.get(k) for k in required):
        raise RuntimeError("更新清单格式无效")
    digest = str(manifest["sha256"]).strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise RuntimeError("更新清单 SHA-256 无效")
    try:
        size = int(manifest["size"])
    except (TypeError, ValueError):
        raise RuntimeError("更新清单文件大小无效")
    if size <= 0:
        raise RuntimeError("更新清单文件大小无效")
    return manifest


def newer_version_available(current_version: str, manifest: dict[str, object]) -> bool:
    return _version_tuple(str(manifest.get("version", "0"))) > _version_tuple(current_version)


def _download_file(
    url: str,
    target: Path,
    timeout: float = 120.0,
    attempts: int = 3,
    *,
    expected_size: int = 0,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            target.unlink(missing_ok=True)
            downloaded = 0
            if progress:
                progress(0, expected_size)
            with urllib.request.urlopen(_request(url), timeout=timeout) as response, target.open("wb") as handle:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    handle.write(block)
                    downloaded += len(block)
                    if progress:
                        progress(downloaded, expected_size)
            if target.stat().st_size <= 0:
                raise RuntimeError("下载到的更新文件为空")
            return
        except Exception as exc:
            last_error = exc
            target.unlink(missing_ok=True)
            if attempt < attempts:
                time.sleep(min(2 * attempt, 5))
    raise RuntimeError(f"下载更新失败（已重试 {attempts} 次）：{last_error}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def stage_update(
    manifest: dict[str, object],
    *,
    progress: Callable[[int, int], None] | None = None,
    phase: Callable[[str], None] | None = None,
) -> Path:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("当前不是已打包 EXE，不能执行自更新")
    update_root = Path(os.getenv("LOCALAPPDATA") or tempfile.gettempdir()) / "win-assistants" / "updates"
    update_root.mkdir(parents=True, exist_ok=True)
    version = str(manifest["version"]).strip().replace("/", "_").replace("\\", "_")
    expected_sha = str(manifest["sha256"]).strip().lower()
    expected_size = int(manifest["size"])
    staged = update_root / f"win-assistants-{version}-{expected_sha[:12]}.exe"
    temp = staged.with_suffix(".download")
    try:
        temp.unlink(missing_ok=True)
        download_url = _cache_busted_url(
            str(manifest["exe_url"]),
            version=version,
            sha256=expected_sha,
        )
        _download_file(download_url, temp, expected_size=expected_size, progress=progress)
        if phase:
            phase("正在校验更新文件…")
        actual_size = temp.stat().st_size
        if actual_size != expected_size:
            raise RuntimeError(
                f"更新文件大小校验失败：应为 {expected_size} 字节，实际 {actual_size} 字节。"
                "可能命中了旧缓存，请稍后重试。"
            )
        digest = _sha256_file(temp)
        if digest != expected_sha:
            raise RuntimeError(
                "更新文件 SHA-256 校验失败。可能命中了旧缓存或下载不完整，请稍后重试。"
            )
        with temp.open("rb") as handle:
            if handle.read(2) != b"MZ":
                raise RuntimeError("更新文件不是有效 Windows EXE")
        temp.replace(staged)
        return staged
    finally:
        temp.unlink(missing_ok=True)


def independent_process_environment() -> dict[str, str]:
    # PyInstaller onefile restarts must unpack a new runtime. The old runtime
    # disappears when the original bootloader exits (PyInstaller >= 6.9).
    environment = os.environ.copy()
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return environment


def verify_staged_startup(staged: Path, timeout: float = 90.0) -> None:
    """Exercise the downloaded one-file bootloader before stopping the running app."""
    marker = staged.with_name(f"startup-check-{os.getpid()}-{time.time_ns()}.txt")
    try:
        process = subprocess.Popen(
            [str(staged), "--smoke-test", str(marker)],
            env=independent_process_environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise RuntimeError("新程序启动检查超时，更新已取消；当前版本仍可使用")
        if process.returncode != 0 or not marker.is_file() or marker.read_text(encoding="ascii") != "ready":
            raise RuntimeError("新程序无法加载运行组件，更新已取消；当前版本仍可使用")
    finally:
        marker.unlink(missing_ok=True)


def _replacement_script(
    source: Path,
    target: Path,
    old_pid: int,
    *,
    expected_sha256: str,
    expected_size: int,
    background: bool = True,
) -> str:
    source_text = str(source).replace("'", "''")
    target_text = str(target).replace("'", "''")
    arguments = "--background" if background else ""
    expected_sha = expected_sha256.replace("'", "''")
    return f"""$ErrorActionPreference = 'Stop'
# Also enforce the public bootloader reset in the helper, including rollback.
$env:PYINSTALLER_RESET_ENVIRONMENT = '1'
$oldPid = {old_pid}
$source = '{source_text}'
$target = '{target_text}'
$expectedSha = '{expected_sha}'
$expectedSize = {expected_size}
$arguments = '{arguments}'
$candidate = "$target.update"
$backup = "$target.previous"
$installedNew = $false
$verifiedStartup = $false
$newProcess = $null
$logDir = Join-Path $env:LOCALAPPDATA 'win-assistants'
$log = Join-Path $logDir 'update.log'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Write-UpdateLog([string]$message) {{
    Add-Content -LiteralPath $log -Value ("$(Get-Date -Format s) " + $message) -Encoding UTF8
}}

try {{
    Write-UpdateLog "begin update pid=$oldPid source=$source target=$target"
    try {{
        Wait-Process -Id $oldPid -Timeout 60 -ErrorAction SilentlyContinue
    }} catch {{}}

    Remove-Item -LiteralPath $candidate -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $source -Destination $candidate -Force

    $size = (Get-Item -LiteralPath $candidate).Length
    if ($size -ne $expectedSize) {{
        throw "candidate size mismatch: expected=$expectedSize actual=$size"
    }}
    $sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $candidate).Hash.ToLowerInvariant()
    if ($sha -ne $expectedSha) {{
        throw "candidate sha256 mismatch: expected=$expectedSha actual=$sha"
    }}

    Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $target -Destination $backup -Force
    for ($attempt = 0; $attempt -lt 30; $attempt++) {{
        try {{
            Move-Item -LiteralPath $candidate -Destination $target -Force
            $installedNew = $true
            break
        }} catch {{
            if ($attempt -ge 29) {{ throw }}
            Start-Sleep -Milliseconds 500
        }}
    }}

    $installedSize = (Get-Item -LiteralPath $target).Length
    $installedSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant()
    if ($installedSize -ne $expectedSize -or $installedSha -ne $expectedSha) {{
        throw "installed file verification failed"
    }}

    Write-UpdateLog "installed sha=$installedSha size=$installedSize"
    $probe = Join-Path $logDir ("startup-" + [guid]::NewGuid().ToString("N") + ".txt")
    $launchArgs = @()
    if ($arguments) {{ $launchArgs += $arguments }}
    $launchArgs += '--update-startup-probe'
    $launchArgs += ('"' + $probe + '"')
    Start-Sleep -Seconds 2
    $newProcess = Start-Process -FilePath $target -ArgumentList $launchArgs -PassThru
    Write-UpdateLog "restart requested pid=$($newProcess.Id)"
    for ($attempt = 0; $attempt -lt 120; $attempt++) {{
        if ((Test-Path -LiteralPath $probe) -and ((Get-Content -LiteralPath $probe -Raw) -eq 'ready')) {{
            $verifiedStartup = $true
            break
        }}
        $newProcess.Refresh()
        if ($newProcess.HasExited) {{ break }}
        Start-Sleep -Milliseconds 500
    }}
    Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
    if (-not $verifiedStartup) {{ throw "new executable did not confirm startup within 60 seconds" }}
    Write-UpdateLog "startup confirmed pid=$($newProcess.Id)"
    Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
}} catch {{
    Write-UpdateLog ("FAILED: " + $_.Exception.Message)
    if ($installedNew -and (Test-Path -LiteralPath $backup)) {{
        try {{
            if ($newProcess -and -not $newProcess.HasExited) {{
                Stop-Process -Id $newProcess.Id -Force -ErrorAction SilentlyContinue
                try {{ Wait-Process -Id $newProcess.Id -Timeout 10 -ErrorAction SilentlyContinue }} catch {{}}
            }}
            Move-Item -LiteralPath $backup -Destination $target -Force
            Write-UpdateLog "rolled back to previous executable"
        }} catch {{
            Write-UpdateLog ("ROLLBACK FAILED: " + $_.Exception.Message)
        }}
    }}
    if (Test-Path -LiteralPath $target) {{
        try {{
            if ($arguments) {{
                $recoveryProcess = Start-Process -FilePath $target -ArgumentList $arguments -PassThru
            }} else {{
                $recoveryProcess = Start-Process -FilePath $target -PassThru
            }}
            Write-UpdateLog "previous restart requested pid=$($recoveryProcess.Id)"
        }} catch {{
            Write-UpdateLog ("restart previous executable failed: " + $_.Exception.Message)
        }}
    }}
}} finally {{
    Remove-Item -LiteralPath $candidate -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $source -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}}
"""


def launch_replacement(
    staged: Path,
    manifest: dict[str, object],
    background: bool = True,
) -> None:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("当前不是已打包 EXE，不能替换程序")
    target = Path(sys.executable).resolve()
    if not staged.is_file():
        raise RuntimeError("待安装更新文件不存在")

    expected_sha = str(manifest["sha256"]).strip().lower()
    expected_size = int(manifest["size"])
    if staged.stat().st_size != expected_size or _sha256_file(staged) != expected_sha:
        raise RuntimeError("待安装更新文件在替换前校验失败")

    script = staged.parent / "apply-update.ps1"
    body = _replacement_script(
        staged,
        target,
        os.getpid(),
        expected_sha256=expected_sha,
        expected_size=expected_size,
        background=background,
    )
    script.write_text(body, encoding="utf-8-sig")
    powershell = Path(os.getenv("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    executable = str(powershell if powershell.is_file() else Path("powershell.exe"))
    subprocess.Popen(
        [
            executable,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(script),
        ],
        env=independent_process_environment(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )



def run_restart_self_test(directory: Path, rollback: bool = False) -> None:
    """Internal packaged acceptance entry; only replace an isolated test copy."""
    import shutil
    from .config import AppConfig
    from .modules import default_module_configs

    directory = directory.resolve()
    target = Path(sys.executable).resolve()
    if not getattr(sys, "frozen", False) or target.parent != directory or not (directory / "acceptance-case").is_file():
        raise RuntimeError("Restart acceptance requires an isolated EXE test copy")
    config = AppConfig.load(default_module_configs())
    for module in config.modules.values():
        module.enabled = False
    config.save()
    (directory / "old-meipass.txt").write_text(str(sys._MEIPASS), encoding="utf-8")
    staging = directory / "updates"
    staging.mkdir()
    source = staging / "candidate.exe"
    if rollback:
        # Fault injection after staging: a valid native PE exits without the
        # application startup probe, forcing the real PowerShell rollback.
        shutil.copy2(Path(os.environ["WINDIR"]) / "System32" / "whoami.exe", source)
    else:
        shutil.copy2(target, source)
        verify_staged_startup(source)
    manifest = {"sha256": _sha256_file(source), "size": source.stat().st_size}
    launch_replacement(source, manifest, background=False)
