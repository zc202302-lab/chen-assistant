import tempfile
import unittest
from pathlib import Path

from win_assistants.config import ModuleConfig
from win_assistants.modules import MODULES, ModuleManager, default_module_configs, internal_sedentary_command


class ModuleTests(unittest.TestCase):
    def test_all_declared_modules_have_defaults(self):
        defaults = default_module_configs()
        self.assertEqual(set(defaults), {item.key for item in MODULES})

    def test_sedentary_default_uses_internal_runtime(self):
        command = internal_sedentary_command()
        self.assertIn("--sedentary", command)
        self.assertIn("--embedded", command)
        self.assertIn("--startup", command)
        defaults = default_module_configs()
        self.assertEqual(defaults["sedentary"].command, command)

    def test_missing_executable_is_not_started(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ModuleManager()
            missing = Path(directory) / "missing.exe"
            ok, detail = manager.start("sms", ModuleConfig(command=[str(missing)]))
        self.assertFalse(ok)
        self.assertIn("找不到程序", detail)


if __name__ == "__main__":
    unittest.main()
