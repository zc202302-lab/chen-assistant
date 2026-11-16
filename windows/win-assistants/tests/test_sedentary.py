from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from win_assistants.sedentary import app_data_dir, read_status, send_command, status_text, tray_text


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


class TrayWorkTimeTests(unittest.TestCase):
    def test_tooltip_duration_and_invalid_status(self):
        self.assertEqual(tray_text({"work_seconds":125}), "已工作2分钟")
        self.assertEqual(tray_text({"work_seconds":59.9}), "已工作0分钟")
        self.assertEqual(tray_text({"work_seconds":-9}), "已工作0分钟")
        for status in [None, {}, {"work_seconds":"bad"}, {"work_seconds":float('nan')}, {"work_seconds":float('inf')}]:
            self.assertEqual(tray_text(status), "win-assistants")

    def test_real_poll_updates_tray_only_on_minute_change(self):
        from types import SimpleNamespace
        from queue import Queue
        from unittest.mock import Mock
        import ast
        import queue
        # Execute the actual polling methods without importing the Tk runtime.
        # The Linux source runner has no libtk; native Windows tests cover Tk UI.
        source=Path(__file__).parents[1]/"win_assistants"/"app.py"
        tree=ast.parse(source.read_text(encoding="utf-8"))
        owner=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="WinAssistantsApp")
        owner.body=[n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name in {"_poll","_refresh_tray_work_time"}]
        namespace={"queue":queue,"sedentary_tray_text":tray_text,"sedentary_status_text":status_text}
        module=ast.Module(body=[ast.ImportFrom(module="__future__",names=[ast.alias(name="annotations")],level=0),owner],type_ignores=[])
        exec(compile(ast.fix_missing_locations(module),str(source),"exec"),namespace)
        WinAssistantsApp=namespace["WinAssistantsApp"]
        class Tray:
            def __init__(self): self.value, self.writes = "win-assistants", []
            @property
            def title(self): return self.value
            @title.setter
            def title(self,value): self.value=value; self.writes.append(value)
        app=WinAssistantsApp.__new__(WinAssistantsApp)
        app.root,app.manager,app.todo_panel=Mock(),Mock(),Mock()
        app.tray_icon=Tray()
        app.status_vars={"sedentary":Mock()}
        app.sms_receiver=SimpleNamespace(events=Queue())
        app.number_inbox_receiver=SimpleNamespace(events=Queue())
        app.todo_receiver=SimpleNamespace(events=Queue())
        app._maybe_show_scheduled_number_reminder=Mock()
        for status in [{"work_seconds":125},{"work_seconds":179},{"work_seconds":180},None]:
            namespace['read_sedentary_status']=Mock(return_value=status)
            app._poll()
        self.assertEqual(app.tray_icon.writes,["已工作2分钟","已工作3分钟","win-assistants"])
        self.assertEqual(app.root.after.call_args.args[0],1500)


if __name__ == "__main__":
    unittest.main()
