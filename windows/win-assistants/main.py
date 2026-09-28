from __future__ import annotations

import sys


def main() -> None:
    if "--sedentary" in sys.argv:
        from sedentary.ui import run as run_sedentary
        run_sedentary()
        return

    from win_assistants.number_inbox import NumberInboxWatcher
    watcher = NumberInboxWatcher()
    watcher.start()
    try:
        from win_assistants.app import run as run_assistants
        run_assistants()
    finally:
        watcher.stop()


if __name__ == "__main__":
    main()
