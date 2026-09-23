from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from win_assistants.sedentary import app_data_dir, read_status, send_command, status_text


class SedentaryBridgeTests(unittest.TestCase):
    def test_read_status_and_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"APPDATA": temp}, clear=False):
            directory = app_data_dir()
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "runtime-status.json").write_text(
                json.dumps(
                    {
                        "updated_at": time.time(),
                        "status": "工作中",
                        "work_seconds": 125,
                        "away_seconds": 0,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            status = read_status()
            self.assertIsNotNone(status)
            self.assertEqual(status_text(status or {}), "工作中 · 2 分钟")

    def test_stale_status_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"APPDATA": temp}, clear=False):
            directory = app_data_dir()
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "runtime-status.json").write_text(
                json.dumps({"updated_at": time.time() - 30, "status": "工作中"}),
                encoding="utf-8",
            )
            self.assertIsNone(read_status(max_age_seconds=8))

    def test_send_settings_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"APPDATA": temp}, clear=False):
            command_id = send_command("show_settings")
            path = Path(temp) / "久坐提醒" / "control-command.json"
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["id"], command_id)
            self.assertEqual(raw["action"], "show_settings")


if __name__ == "__main__":
    unittest.main()
