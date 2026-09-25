from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from sedentary.control_bridge import consume_control_command, read_runtime_status, send_control_command, write_runtime_status


class ControlBridgeTests(unittest.TestCase):
    def test_status_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"APPDATA": temp}, clear=False):
            write_runtime_status({"status": "工作中", "work_seconds": 61})
            status = read_runtime_status()
            self.assertIsNotNone(status)
            self.assertEqual(status["status"], "工作中")
            self.assertEqual(status["work_seconds"], 61)
            self.assertIn("pid", status)

    def test_command_is_consumed_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"APPDATA": temp}, clear=False):
            command_id = send_control_command("show_settings")
            command = consume_control_command()
            self.assertIsNotNone(command)
            self.assertEqual(command["id"], command_id)
            self.assertEqual(command["action"], "show_settings")
            self.assertIsNone(consume_control_command())

    def test_stale_command_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"APPDATA": temp}, clear=False):
            send_control_command("show_status")
            path = os.path.join(temp, "久坐提醒", "control-command.json")
            raw = json.loads(open(path, "r", encoding="utf-8").read())
            raw["created_at"] = time.time() - 30
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(raw, handle)
            self.assertIsNone(consume_control_command(max_age_seconds=10))


if __name__ == "__main__":
    unittest.main()
