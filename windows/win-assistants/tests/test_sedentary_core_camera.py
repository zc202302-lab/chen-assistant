import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
from sedentary.storage import Settings
from sedentary.camera import PresenceDetector

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

    def test_configured_presence_requires_continuous_detection(self):
        debouncer = PresenceDebouncer(absence_seconds=1, presence_seconds=5)
        debouncer.update(False, 0)
        self.assertFalse(debouncer.update(False, 1))
        self.assertFalse(debouncer.update(True, 2))
        self.assertFalse(debouncer.update(True, 6.9))
        self.assertFalse(debouncer.update(False, 7))
        self.assertFalse(debouncer.update(True, 8))
        self.assertFalse(debouncer.update(True, 12.9))
        self.assertTrue(debouncer.update(True, 13))

    def test_presence_confirmation_keeps_absence_confirmation(self):
        debouncer = PresenceDebouncer(absence_seconds=8, presence_seconds=5)
        self.assertTrue(debouncer.update(False, 0))
        self.assertFalse(debouncer.update(False, 8))
        self.assertFalse(debouncer.update(True, 9))
        self.assertTrue(debouncer.update(True, 14))
        self.assertTrue(debouncer.update(False, 15))
        self.assertTrue(debouncer.update(False, 22.9))
        self.assertFalse(debouncer.update(False, 23))


class PresenceSettingsTests(unittest.TestCase):
    def test_old_settings_migrate_and_new_value_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "settings.json").write_text(json.dumps({"absence_grace_seconds": 8}))
            with patch("sedentary.storage.app_data_dir", return_value=root), patch("sedentary.storage.load_windows_secret", return_value=""), patch("sedentary.storage.save_windows_secret"):
                settings = Settings.load()
                self.assertEqual(settings.presence_grace_seconds, 1)
                settings.presence_grace_seconds = 5
                settings.save()
                self.assertEqual(Settings.load().presence_grace_seconds, 5)
                self.assertEqual(Settings.load().absence_grace_seconds, 8)

    def test_detector_accepts_configured_confirmation(self):
        detector = PresenceDetector("rtsp://camera", 1, 8, lambda status: None, presence_grace=5)
        self.assertEqual(detector.presence_grace, 5)


class DetectorModelTests(unittest.TestCase):
    def test_real_models_load_from_chinese_frozen_path_with_stale_cv2_path(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("OpenCV is exercised by the Windows build")
        import shutil
        with tempfile.TemporaryDirectory(prefix="晨的助手 模型 ") as directory:
            root = Path(directory)
            models = root / "cv2" / "data"
            shutil.copytree(cv2.data.haarcascades, models)
            with patch("sedentary.camera.sys.frozen", True, create=True), \
                 patch("sedentary.camera.sys._MEIPASS", str(root), create=True), \
                 patch.object(cv2.data, "haarcascades", str(root / "missing")), \
                 patch.object(cv2, "__file__", str(root / "stale" / "cv2.py")):
                # Enforce that no model filename is passed to native OpenCV I/O.
                constructor = cv2.CascadeClassifier
                def memory_only(*args):
                    self.assertFalse(args, "Native OpenCV must not open Unicode filenames")
                    return constructor()
                with patch.object(cv2, "CascadeClassifier", side_effect=memory_only):
                    cascades, hog = PresenceDetector._load_detectors(cv2)
                self.assertEqual(len(cascades), 5)
                self.assertTrue(all(not classifier.empty() for _, classifier in cascades))
                self.assertIsNone(PresenceDetector._detect_in_region(
                    cv2, np.zeros((256, 256, 3), dtype=np.uint8), cascades, hog))

    def test_missing_models_fail_closed_and_log_details(self):
        try:
            import cv2
        except ImportError:
            self.skipTest("OpenCV is exercised by the Windows build")
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(cv2.data, "haarcascades", directory), \
             patch.object(cv2, "__file__", str(Path(directory) / "cv2.py")), \
             patch("sedentary.camera.sys.frozen", False, create=True), \
             patch("sedentary.camera._write_detector_error") as log:
            cascades, _ = PresenceDetector._load_detectors(cv2)
            self.assertEqual(cascades, [])
            self.assertIn("haarcascade_frontalface_default.xml", log.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
