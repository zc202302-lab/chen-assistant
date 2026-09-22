import tempfile
import unittest
from pathlib import Path

from win_assistants.config import ModuleConfig
from win_assistants.modules import MODULES, ModuleManager, default_module_configs


class ModuleTests(unittest.TestCase):
    def test_all_declared_modules_have_defaults(self):
        defaults = default_module_configs()
        self.assertEqual(set(defaults), {item.key for item in MODULES})

    def test_missing_executable_is_not_started(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ModuleManager()
            missing = Path(directory) / "missing.exe"
            ok, detail = manager.start("sms", ModuleConfig(command=[str(missing)]))
        self.assertFalse(ok)
        self.assertIn("找不到程序", detail)


if __name__ == "__main__":
    unittest.main()
