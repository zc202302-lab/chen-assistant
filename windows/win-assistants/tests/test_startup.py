from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from win_assistants.startup import startup_command


class StartupTests(unittest.TestCase):
    def test_frozen_startup_is_silent_tray_mode(self) -> None:
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", r"C:\Tools\win-assistants.exe"):
            command = startup_command()
        self.assertIn(r'"C:\Tools\win-assistants.exe"', command)
        self.assertTrue(command.endswith(" --background"))

    def test_source_startup_is_silent_tray_mode(self) -> None:
        with patch.object(sys, "frozen", False, create=True):
            command = startup_command()
        self.assertIn("--background", command)
        self.assertIn("main.py", command)


if __name__ == "__main__":
    unittest.main()
