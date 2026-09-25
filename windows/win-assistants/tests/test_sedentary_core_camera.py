import unittest

from sedentary.camera import PresenceDebouncer, build_rtsp_url, normalize_roi


class CameraUrlTests(unittest.TestCase):
    def test_builds_ct3_url(self):
        result = build_rtsp_url("192.168.1.20", 8554, "/rtsp_live1", "admin", "secret")
        self.assertEqual(result, "rtsp://admin:secret@192.168.1.20:8554/rtsp_live1")

    def test_encodes_credentials_and_normalizes_path(self):
        result = build_rtsp_url("camera.local", 554, "stream2", "a@b", "p:/ x")
        self.assertEqual(result, "rtsp://a%40b:p%3A%2F%20x@camera.local:554/stream2")

    def test_normalize_roi(self):
        self.assertEqual(normalize_roi((10, 20, 50, 40), 100, 100), [0.1, 0.2, 0.5, 0.4])

    def test_normalize_roi_rejects_cancelled_selection(self):
        self.assertIsNone(normalize_roi((0, 0, 0, 0), 100, 100))


class PresenceDebouncerTests(unittest.TestCase):
    def test_starts_fail_safe_as_present(self):
        debouncer = PresenceDebouncer(absence_seconds=3)
        self.assertTrue(debouncer.state)

    def test_short_detector_miss_does_not_count_as_away(self):
        debouncer = PresenceDebouncer(absence_seconds=3)
        self.assertTrue(debouncer.update(False, 0.0))
        self.assertTrue(debouncer.update(False, 2.9))
        self.assertTrue(debouncer.update(True, 3.0))
        self.assertTrue(debouncer.state)

    def test_sustained_absence_switches_to_away(self):
        debouncer = PresenceDebouncer(absence_seconds=3)
        self.assertTrue(debouncer.update(False, 0.0))
        self.assertTrue(debouncer.update(False, 2.9))
        self.assertFalse(debouncer.update(False, 3.0))
        self.assertFalse(debouncer.state)

    def test_presence_returns_after_confirmation(self):
        debouncer = PresenceDebouncer(absence_seconds=1, presence_seconds=0.5)
        debouncer.update(False, 0.0)
        self.assertFalse(debouncer.update(False, 1.0))
        self.assertFalse(debouncer.update(True, 2.0))
        self.assertTrue(debouncer.update(True, 2.5))
        self.assertTrue(debouncer.state)


if __name__ == "__main__":
    unittest.main()
