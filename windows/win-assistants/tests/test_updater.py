from __future__ import annotations

import unittest

from pathlib import Path

from win_assistants.updater import _replacement_script, _version_tuple, newer_version_available


class UpdaterTests(unittest.TestCase):
    def test_version_tuple(self) -> None:
        self.assertEqual(_version_tuple("v0.4.0"), (0, 4, 0))
        self.assertEqual(_version_tuple("1.2.3"), (1, 2, 3))

    def test_replacement_restarts_in_background(self) -> None:
        script = _replacement_script(Path(r"C:\Tools\new.exe"), Path(r"C:\Tools\win-assistants.exe"), 123)
        self.assertIn("$arguments = '--background'", script)
        self.assertIn("Start-Process -FilePath $target -ArgumentList $arguments", script)

    def test_replacement_can_restart_visible(self) -> None:
        script = _replacement_script(Path(r"C:\Tools\new.exe"), Path(r"C:\Tools\win-assistants.exe"), 123, background=False)
        self.assertIn("$arguments = ''", script)

    def test_newer_version(self) -> None:
        self.assertTrue(newer_version_available("0.3.2", {"version": "0.4.0"}))
        self.assertFalse(newer_version_available("0.4.0", {"version": "0.4.0"}))
        self.assertFalse(newer_version_available("0.4.1", {"version": "0.4.0"}))


if __name__ == "__main__":
    unittest.main()
