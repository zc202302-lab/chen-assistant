from __future__ import annotations

import io
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from win_assistants.updater import (
    _cache_busted_url,
    _download_file,
    _replacement_script,
    _version_tuple,
    newer_version_available,
    verify_staged_startup,
    independent_process_environment,
    launch_replacement,
)


class UpdaterTests(unittest.TestCase):
    def test_restart_environment_resets_bootloader_without_changing_parent(self) -> None:
        with patch.dict("os.environ", {"_PYI_APPLICATION_HOME_DIR": "old-runtime",
                                      "PYINSTALLER_RESET_ENVIRONMENT": "0"}):
            environment = independent_process_environment()
            self.assertEqual(environment["PYINSTALLER_RESET_ENVIRONMENT"], "1")
            self.assertEqual(__import__("os").environ["PYINSTALLER_RESET_ENVIRONMENT"], "0")

    def test_replacement_helper_receives_independent_environment(self) -> None:
        import hashlib
        import sys
        with tempfile.TemporaryDirectory() as directory:
            staged = Path(directory) / "candidate.exe"
            staged.write_bytes(b"MZ-candidate")
            manifest = {"sha256": hashlib.sha256(staged.read_bytes()).hexdigest(),
                        "size": staged.stat().st_size}
            with patch.object(sys, "frozen", True, create=True), patch(
                    "win_assistants.updater.subprocess.Popen") as launch:
                launch_replacement(staged, manifest)
            self.assertEqual(launch.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")
            self.assertIn("$env:PYINSTALLER_RESET_ENVIRONMENT = '1'",
                          (staged.parent / "apply-update.ps1").read_text(encoding="utf-8-sig"))

    def test_version_tuple(self) -> None:
        self.assertEqual(_version_tuple("v0.4.0"), (0, 4, 0))
        self.assertEqual(_version_tuple("1.2.3"), (1, 2, 3))

    def test_cache_busted_url_keeps_existing_query_and_adds_identity(self) -> None:
        url = _cache_busted_url(
            "https://example.test/win-assistants.exe?source=manifest",
            version="0.5.2",
            sha256="a" * 64,
        )
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        self.assertEqual(query["source"], ["manifest"])
        self.assertEqual(query["version"], ["0.5.2"])
        self.assertEqual(query["sha"], ["a" * 16])
        self.assertTrue(query["nocache"][0].isdigit())

    def test_download_reports_actual_bytes(self) -> None:
        events: list[tuple[int, int]] = []
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "update.download"
            with patch("win_assistants.updater.urllib.request.urlopen",
                       return_value=io.BytesIO(b"abcde")):
                _download_file("https://example.test/app.exe", target,
                               expected_size=5, progress=lambda done, total: events.append((done, total)))
            self.assertEqual(target.read_bytes(), b"abcde")
        self.assertEqual(events, [(0, 5), (5, 5)])

    def test_failed_staged_startup_keeps_current_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate.exe"
            candidate.write_bytes(b"MZ")
            process = unittest.mock.Mock()
            process.returncode = 1
            with patch("win_assistants.updater.subprocess.Popen", return_value=process):
                with self.assertRaisesRegex(RuntimeError, "当前版本仍可使用"):
                    verify_staged_startup(candidate)
            self.assertTrue(candidate.exists())

    def test_startup_preflight_also_uses_fresh_bootloader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staged = Path(directory) / "candidate.exe"
            staged.write_bytes(b"MZ")
            process = unittest.mock.Mock(returncode=1)
            with patch("win_assistants.updater.subprocess.Popen", return_value=process) as launch:
                with self.assertRaises(RuntimeError):
                    verify_staged_startup(staged)
            self.assertEqual(launch.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_replacement_restarts_in_background_and_verifies_candidate(self) -> None:
        script = _replacement_script(
            Path(r"C:\Tools\new.exe"),
            Path(r"C:\Tools\win-assistants.exe"),
            123,
            expected_sha256="b" * 64,
            expected_size=71621269,
        )
        self.assertIn("$arguments = '--background'", script)
        self.assertIn('$candidate = "$target.update"', script)
        self.assertIn("Get-FileHash -Algorithm SHA256", script)
        self.assertIn("$expectedSize = 71621269", script)
        self.assertIn("$expectedSha = '" + ("b" * 64) + "'", script)
        self.assertIn("Move-Item -LiteralPath $candidate -Destination $target -Force", script)
        self.assertIn("Start-Process -FilePath $target -ArgumentList $arguments", script)
        self.assertIn("update.log", script)
        self.assertIn("startup confirmed", script)
        self.assertIn("--update-startup-probe", script)
        self.assertIn("rolled back to previous executable", script)
        self.assertIn("Move-Item -LiteralPath $backup -Destination $target -Force", script)

    def test_replacement_can_restart_visible(self) -> None:
        script = _replacement_script(
            Path(r"C:\Tools\new.exe"),
            Path(r"C:\Tools\win-assistants.exe"),
            123,
            expected_sha256="c" * 64,
            expected_size=1234,
            background=False,
        )
        self.assertIn("$arguments = ''", script)

    def test_newer_version(self) -> None:
        self.assertTrue(newer_version_available("0.5.2", {"version": "0.5.3"}))
        self.assertFalse(newer_version_available("0.5.3", {"version": "0.5.3"}))
        self.assertFalse(newer_version_available("0.5.4", {"version": "0.5.3"}))


if __name__ == "__main__":
    unittest.main()

