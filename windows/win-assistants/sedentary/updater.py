from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _git_cache_path() -> Path:
    return project_root() / ".git-path.txt"


def _valid_git(path: str | Path | None) -> str | None:
    if not path:
        return None
    candidate = str(path)
    try:
        result = subprocess.run(
            [candidate, "--version"],
            cwd=str(project_root()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )
        if result.returncode == 0:
            return candidate
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _registry_git_candidates() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    candidates: list[str] = []
    roots = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]
    subkeys = [
        r"SOFTWARE\GitForWindows",
        r"SOFTWARE\WOW6432Node\GitForWindows",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\git.exe",
    ]
    for root in roots:
        for subkey in subkeys:
            try:
                with winreg.OpenKey(root, subkey) as key:
                    if subkey.endswith("git.exe"):
                        value, _ = winreg.QueryValueEx(key, None)
                        candidates.append(str(value))
                    else:
                        install, _ = winreg.QueryValueEx(key, "InstallPath")
                        candidates.extend([
                            str(Path(install) / "cmd" / "git.exe"),
                            str(Path(install) / "bin" / "git.exe"),
                        ])
            except OSError:
                continue
    return candidates


def _common_git_candidates() -> list[str]:
    env = os.environ
    pf = Path(env.get("ProgramFiles", r"C:\Program Files"))
    pfx86 = Path(env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    local = Path(env.get("LOCALAPPDATA", ""))
    home = Path.home()
    root = project_root()

    paths = [
        pf / "Git" / "cmd" / "git.exe",
        pf / "Git" / "bin" / "git.exe",
        pfx86 / "Git" / "cmd" / "git.exe",
        local / "Programs" / "Git" / "cmd" / "git.exe",
        local / "Programs" / "Git" / "bin" / "git.exe",
        home / "scoop" / "apps" / "git" / "current" / "cmd" / "git.exe",
        Path(env.get("ProgramData", r"C:\ProgramData")) / "chocolatey" / "bin" / "git.exe",
        root.parent / "Git" / "cmd" / "git.exe",
        root.parent / "Git" / "bin" / "git.exe",
    ]
    if sys.platform == "win32":
        github_desktop = local / "GitHubDesktop"
        if github_desktop.exists():
            try:
                for path in github_desktop.glob("app-*/resources/app/git/cmd/git.exe"):
                    paths.append(path)
                for path in github_desktop.glob("app-*/resources/app/git/bin/git.exe"):
                    paths.append(path)
            except OSError:
                pass

        for drive in ("C:", "D:", "E:", "F:"):
            base = Path(drive + "\\")
            paths.extend([
                base / "Program Files" / "Git" / "cmd" / "git.exe",
                base / "Program Files" / "Git" / "bin" / "git.exe",
                base / "Git" / "cmd" / "git.exe",
                base / "Git" / "bin" / "git.exe",
                base / "Tools" / "Git" / "cmd" / "git.exe",
                base / "Tools" / "Git" / "bin" / "git.exe",
            ])
    return [str(p) for p in paths]


def _targeted_git_scan() -> list[str]:
    if sys.platform != "win32":
        return []

    roots: list[Path] = []
    env = os.environ
    for candidate in [
        project_root().parent,
        Path(env.get("LOCALAPPDATA", "")) / "Programs",
        Path(env.get("USERPROFILE", "")) / "scoop" / "apps",
        Path(r"C:\Program Files"),
        Path(r"D:\Program Files"),
        Path(r"D:\Tools"),
        Path(r"E:\Program Files"),
        Path(r"E:\Tools"),
        Path(r"F:\Program Files"),
        Path(r"F:\Tools"),
    ]:
        if str(candidate) and candidate.exists():
            roots.append(candidate)

    found: list[str] = []
    for root in roots:
        base_depth = len(root.parts)
        try:
            for current, dirs, files in os.walk(root):
                current_path = Path(current)
                depth = len(current_path.parts) - base_depth
                if depth > 5:
                    dirs[:] = []
                    continue
                lowered = {name.lower() for name in files}
                if "git.exe" in lowered:
                    path = current_path / "git.exe"
                    if "git" in str(path).lower():
                        found.append(str(path))
        except OSError:
            continue
    return found


def cache_git_path(path: str | Path) -> tuple[bool, str]:
    valid = _valid_git(path)
    if not valid:
        return False, "选择的文件不是可用的 Git 程序。"
    try:
        _git_cache_path().write_text(valid, encoding="utf-8")
    except OSError as exc:
        return False, f"保存 Git 路径失败：{exc}"
    return True, valid


def find_git() -> str | None:
    candidates: list[str] = []

    cache = _git_cache_path()
    try:
        if cache.exists():
            candidates.append(cache.read_text(encoding="utf-8", errors="ignore").strip())
    except OSError:
        pass

    which = shutil.which("git")
    if which:
        candidates.append(which)

    candidates.extend(_registry_git_candidates())
    candidates.extend(_common_git_candidates())
    candidates.extend(_targeted_git_scan())

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        key = os.path.normcase(os.path.normpath(candidate))
        if key in seen:
            continue
        seen.add(key)
        valid = _valid_git(candidate)
        if valid:
            try:
                cache.write_text(valid, encoding="utf-8")
            except OSError:
                pass
            return valid
    return None


def _run_git(git: str, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [git, *args],
        cwd=str(project_root()),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
    )


def check_and_update() -> tuple[str, str]:
    """Check and fast-forward the private GitHub clone using a verified Git path."""
    git = find_git()
    if not git:
        return (
            "git_missing",
            "未自动找到 Git。可手动选择一次 git.exe，程序会永久记住该路径。"
        )

    try:
        fetch = _run_git(git, "fetch", "origin", "main", timeout=60)
        if fetch.returncode != 0:
            detail = (fetch.stderr or fetch.stdout or "").strip()
            return "offline", "无法从 GitHub 获取更新。" + (f" {detail[-220:]}" if detail else "")

        local = _run_git(git, "rev-parse", "HEAD", timeout=10)
        remote = _run_git(git, "rev-parse", "origin/main", timeout=10)
        if local.returncode != 0 or remote.returncode != 0:
            return "error", "无法读取本地或远程版本信息。"

        local_sha = local.stdout.strip()
        remote_sha = remote.stdout.strip()
        if local_sha == remote_sha:
            return "current", "当前已经是最新版本。"

        merge = _run_git(git, "merge", "--ff-only", "origin/main", timeout=60)
        if merge.returncode != 0:
            detail = (merge.stderr or merge.stdout or "").strip()
            return "error", "更新失败：" + (detail[-300:] if detail else "无法快进合并。")

        return "updated", "发现新版本并已更新完成。"
    except (OSError, subprocess.SubprocessError) as exc:
        return "error", f"更新检查失败：{exc}"


def restart_app() -> tuple[bool, str]:
    root = project_root()
    main_py = root / "main.py"

    if sys.platform == "win32":
        python_exe = root / ".venv" / "Scripts" / "pythonw.exe"
        if not python_exe.exists():
            python_exe = root / ".venv" / "Scripts" / "python.exe"
    else:
        python_exe = Path(sys.executable)

    if not main_py.exists():
        return False, f"找不到主程序：{main_py}"
    if not python_exe.exists():
        return False, f"找不到 Python 运行环境：{python_exe}"

    try:
        if sys.platform == "win32":
            flags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            # Delay the real app launch so the current process can exit and
            # release the single-instance mutex first.
            requirements = root / "requirements.txt"
            python_console = root / ".venv" / "Scripts" / "python.exe"
            helper_python = python_console if python_console.exists() else python_exe
            helper_code = (
                "import subprocess,time,pathlib;"
                "time.sleep(1.5);"
                f"root=pathlib.Path({str(root)!r});"
                f"py={str(python_console)!r};"
                f"req={str(requirements)!r};"
                "subprocess.run([py,'-m','pip','install','--disable-pip-version-check','-r',req],"
                "cwd=str(root),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=180,check=False);"
                f"subprocess.Popen({[str(python_exe), str(main_py)]!r}, "
                f"cwd={str(root)!r}, close_fds=True, creationflags={flags})"
            )
            subprocess.Popen(
                [str(helper_python), "-c", helper_code],
                cwd=str(root),
                close_fds=True,
                creationflags=flags,
            )
            return True, "新版程序将在当前程序退出、依赖刷新后自动启动。"

        subprocess.Popen(
            [str(python_exe), str(main_py)],
            cwd=str(root),
            close_fds=True,
            start_new_session=True,
        )
        return True, "新版程序已启动。"
    except OSError as exc:
        return False, f"自动重启失败：{exc}"
