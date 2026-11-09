from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if "--update-restart-self-test" in sys.argv:
        index = sys.argv.index("--update-restart-self-test") + 1
        from win_assistants.updater import run_restart_self_test
        run_restart_self_test(Path(sys.argv[index]), rollback="--test-rollback" in sys.argv)
        return

    if "--smoke-test" in sys.argv:
        index = sys.argv.index("--smoke-test") + 1
        if index >= len(sys.argv):
            raise SystemExit("smoke marker path required")
        import tkinter
        from win_assistants import app
        from sedentary import ui
        assert tkinter and app and ui
        import cv2
        import numpy as np
        from sedentary.camera import PresenceDetector
        cascades, hog = PresenceDetector._load_detectors(cv2)
        if len(cascades) != 5:
            raise RuntimeError("Packaged OpenCV detection models are missing or unreadable")
        # Exercise native classifiers as well as parsing their XML.
        PresenceDetector._detect_in_region(cv2, np.zeros((256, 256, 3), dtype=np.uint8), cascades, hog)
        Path(sys.argv[index]).write_text("ready", encoding="ascii")
        return

    if "--sedentary" in sys.argv:
        from sedentary.ui import run as run_sedentary
        run_sedentary()
        return

    from win_assistants.app import run as run_assistants
    run_assistants()


if __name__ == "__main__":
    main()

