"""Exercise update failures after the worker's exception scope has ended."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class UpdateErrorCallbacksTests(unittest.TestCase):
    def test_check_and_download_errors_survive_ui_dispatch(self):
        source = Path(__file__).parents[1] / "win_assistants" / "app.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        methods = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        for name, failing_call, dialog in [
            ("_check_updates", "fetch_manifest", "showwarning"),
            ("_download_and_apply_update", "stage_update", "showerror"),
        ]:
            with self.subTest(name=name):
                callbacks = []
                statuses = []
                boxes = Mock()
                thread = Mock()
                thread.start.side_effect = lambda: thread.target()
                def make_thread(**kwargs):
                    thread.target = kwargs["target"]
                    return thread
                namespace = {
                    failing_call: Mock(side_effect=OSError("runtime archive missing")),
                    "threading": SimpleNamespace(Thread=make_thread),
                    "messagebox": boxes,
                }
                module = ast.Module(body=[methods[name]], type_ignores=[])
                exec(compile(module, str(source), "exec"), namespace)
                app = SimpleNamespace(
                    root=SimpleNamespace(after=lambda delay, callback: callbacks.append(callback)),
                    _finish_update_check=statuses.append,
                )
                args = (app,) if name == "_check_updates" else (app, {})
                namespace[name](*args)
                self.assertEqual(len(callbacks), 1)
                callbacks.pop()()
                self.assertIn("runtime archive missing", statuses[-1])
                self.assertIn("runtime archive missing", getattr(boxes, dialog).call_args.args[1])


if __name__ == "__main__":
    unittest.main()
