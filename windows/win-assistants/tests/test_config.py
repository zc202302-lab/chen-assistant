import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from win_assistants.config import AppConfig, ModuleConfig, NumberInboxConfig


class ConfigTests(unittest.TestCase):
    def test_module_config_rejects_non_string_command(self):
        cfg = ModuleConfig.from_dict({"enabled": True, "command": ["ok", 3], "delay_seconds": 999})
        self.assertEqual(cfg.command, [])
        self.assertEqual(cfg.delay_seconds, 120)

    def test_app_config_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with patch("win_assistants.config.app_data_dir", return_value=target):
                original = AppConfig(start_minimized=False, modules={"sms": ModuleConfig(True, ["sms.exe"], 3)}, number_inbox=NumberInboxConfig(api_url="https://example.test/api", protected_token="portable:dGVzdA==", interval_seconds=17, last_seen_id=42))
                original.save()
                loaded = AppConfig.load()
            self.assertFalse(loaded.start_minimized)
            self.assertEqual(loaded.modules["sms"].command, ["sms.exe"])
            raw = json.loads((target / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(raw["modules"]["sms"]["delay_seconds"], 3)
            self.assertEqual(loaded.number_inbox.api_url, "https://example.test/api")
            self.assertEqual(loaded.number_inbox.interval_seconds, 17)
            self.assertEqual(loaded.number_inbox.last_seen_id, 42)


if __name__ == "__main__":
    unittest.main()
