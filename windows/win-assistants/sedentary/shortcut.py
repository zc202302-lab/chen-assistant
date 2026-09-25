from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _ps_quote(value: str) -> str:
    return value.replace("'", "''")


def create_desktop_shortcut() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "当前系统不是 Windows。"

    root = project_root()
    pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
    main_py = root / "main.py"
    if not pythonw.exists():
        return False, "尚未找到运行环境，请先正常启动程序一次。"

    # Let Windows resolve the real Desktop folder (including OneDrive redirection).
    script = f"""
$ws = New-Object -ComObject WScript.Shell
$desktop = $ws.SpecialFolders.Item('Desktop')
$shortcut = Join-Path $desktop '晨·久坐守护.lnk'
$s = $ws.CreateShortcut($shortcut)
$s.TargetPath = '{_ps_quote(str(pythonw))}'
$s.Arguments = '"{_ps_quote(str(main_py))}"'
$s.WorkingDirectory = '{_ps_quote(str(root))}'
$s.IconLocation = '{_ps_quote(str(pythonw))},0'
$s.Save()
Write-Output $shortcut
""".strip()

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            suffix=".ps1",
            delete=False,
        ) as handle:
            handle.write(script)
            temp_path = Path(handle.name)

        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(temp_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"创建快捷方式失败：{exc}"
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass

    detail = (result.stderr or result.stdout or "").strip()
    if result.returncode != 0:
        return False, "创建快捷方式失败。" + (f" {detail[-200:]}" if detail else "")
    return True, "桌面快捷方式已创建：晨·久坐守护.lnk"
