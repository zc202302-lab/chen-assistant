import sys
import unittest
from pathlib import Path

from win_assistants.app import _command_for_path, _display_path


class AppCommandTests(unittest.TestCase):
    def test_python_module_keeps_script_as_display_path(self):
        command = _command_for_path("sedentary", r"D:\Tools\chen-sit-guard\main.py")
        self.assertTrue(command[0].lower().endswith(("python", "python.exe", "pythonw.exe")) or command[0] == sys.executable)
        self.assertEqual(_display_path(command), r"D:\Tools\chen-sit-guard\main.py")
        self.assertEqual(command[-1], "--startup")

    def test_powershell_module_keeps_script_as_display_path(self):
        script = r"C:\Users\Chen\AppData\Local\ChenAssistant\chen_foxmail_bootstrap.ps1"
        command = _command_for_path("chen_helper", script)
        self.assertEqual(_display_path(command), script)
        self.assertIn("-Watch", command)

    def test_sms_executable_uses_background_mode(self):
        executable = r"D:\Tools\iPhone验证码助手-图标版.exe"
        command = _command_for_path("sms", executable)
        self.assertEqual(command, [executable, "--background"])
        self.assertEqual(_display_path(command), executable)


if __name__ == "__main__":
    unittest.main()
