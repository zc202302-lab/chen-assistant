from __future__ import annotations

import unittest

from win_assistants.updater import _version_tuple, newer_version_available


class UpdaterTests(unittest.TestCase):
    def test_version_tuple(self) -> None:
        self.assertEqual(_version_tuple("v0.4.0"), (0, 4, 0))
        self.assertEqual(_version_tuple("1.2.3"), (1, 2, 3))

    def test_newer_version(self) -> None:
        self.assertTrue(newer_version_available("0.3.2", {"version": "0.4.0"}))
        self.assertFalse(newer_version_available("0.4.0", {"version": "0.4.0"}))
        self.assertFalse(newer_version_available("0.4.1", {"version": "0.4.0"}))


if __name__ == "__main__":
    unittest.main()
