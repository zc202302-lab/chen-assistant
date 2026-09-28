from __future__ import annotations

import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from win_assistants.updater import (
    _cache_busted_url,
    _replacement_script,
    _version_tuple,
    newer_version_available,
)


class UpdaterTests(unittest.TestCase):
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
        self.assertTrue(newer_version_available("0.5.1", {"version": "0.5.2"}))
        self.assertFalse(newer_version_available("0.5.2", {"version": "0.5.2"}))
        self.assertFalse(newer_version_available("0.5.3", {"version": "0.5.2"}))


if __name__ == "__main__":
    unittest.main()
