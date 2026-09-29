from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if "--smoke-test" in sys.argv:
        # The frozen executable must start Python and import its bundled modules.
        # A marker is stronger evidence than a GUI process merely staying alive.
        marker_index = sys.argv.index("--smoke-test") + 1
        if marker_index >= len(sys.argv):
            raise SystemExit("smoke marker path required")
        import tkinter
        from win_assistants import app
        from sedentary import ui
        assert tkinter and app and ui
        Path(sys.argv[marker_index]).write_text("ready", encoding="ascii")
        return

    if "--sedentary" in sys.argv:
        from sedentary.ui import run as run_sedentary
        run_sedentary()
        return

    from win_assistants.app import run as run_assistants
    run_assistants()


if __name__ == "__main__":
    main()
