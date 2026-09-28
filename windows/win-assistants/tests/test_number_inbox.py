from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from win_assistants.number_inbox import NumberInboxWatcher, fetch_pending_count


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit):
        return json.dumps({"ok": True, "pending_count": 3}).encode("utf-8")


class NumberInboxTests(unittest.TestCase):
    @patch("win_assistants.number_inbox.urllib.request.urlopen", return_value=_Response())
    def test_fetch_pending_count(self, _urlopen):
        self.assertEqual(fetch_pending_count(), 3)

    def test_interval_has_safe_floor(self):
        self.assertEqual(NumberInboxWatcher(interval_seconds=1).interval_seconds, 10)


if __name__ == "__main__":
    unittest.main()
