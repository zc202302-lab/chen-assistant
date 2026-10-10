from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import quote


@dataclass(frozen=True)
class CameraStatus:
    available: bool
    present: bool
    message: str


def build_rtsp_url(host: str, port: int, path: str, username: str, password: str) -> str:
    host = host.strip()
    path = path.strip()
    if not path.startswith("/"):
        path = "/" + path
    credentials = ""
    if username:
        credentials = quote(username, safe="")
        if password:
            credentials += ":" + quote(password, safe="")
        credentials += "@"
    return f"rtsp://{credentials}{host}:{int(port)}{path}"


_OPEN_LOCK = threading.Lock()


def _capture_params(cv2) -> list[int]:
    params: list[int] = []
    if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
        params += [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000]
    if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
        params += [cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000]
    return params


def _open_one(stream_url: str, transport: str, backend: int):
    import cv2

    if transport == "tcp":
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"
    elif transport == "udp":
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;udp|stimeout;5000000"
    else:
        os.environ.pop("OPENCV_FFMPEG_CAPTURE_OPTIONS", None)

    params = _capture_params(cv2)
    try:
        if backend == cv2.CAP_FFMPEG and params:
            return cv2.VideoCapture(stream_url, backend, params)
        return cv2.VideoCapture(stream_url, backend)
    except (TypeError, cv2.error):
        try:
            return cv2.VideoCapture(stream_url, backend)
        except cv2.error:
            return None


def connect_rtsp(stream_url: str, per_attempt_seconds: float = 3.0):
    """Return (capture, first_frame, transport_label), or (None, None, reason).

    Connection is accepted only after a real frame is decoded. TCP, UDP,
    FFmpeg automatic negotiation and OpenCV's default backend are tried.
    """
    import cv2

    attempts = [
        ("TCP", "tcp", cv2.CAP_FFMPEG),
        ("UDP", "udp", cv2.CAP_FFMPEG),
        ("自动", "auto", cv2.CAP_FFMPEG),
        ("默认后端", "default", cv2.CAP_ANY),
    ]

    with _OPEN_LOCK:
        for label, transport, backend in attempts:
            capture = _open_one(stream_url, transport, backend)
            if capture is None:
                continue
            try:
                if not capture.isOpened():
                    capture.release()
                    continue
                if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
                    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                deadline = time.monotonic() + max(1.0, per_attempt_seconds)
                while time.monotonic() < deadline:
                    ok, frame = capture.read()
                    if ok and frame is not None and frame.size > 0:
                        return capture, frame, label
                    time.sleep(0.05)
            except cv2.error:
                pass
            capture.release()

    return None, None, "TCP/UDP/自动协商均未读取到视频帧"


def test_rtsp_connection(stream_url: str) -> tuple[bool, str]:
    capture, frame, transport = connect_rtsp(stream_url, 3.0)
    if capture is None or frame is None:
        return False, f"无法读取视频流：{transport}。"
    try:
        return True, f"连接成功，已经读取到视频画面（{transport}）。"
    finally:
        capture.release()
        del frame


def capture_frame(stream_url: str, timeout_seconds: float = 8.0):
    """Capture one verified RTSP frame."""
    per_attempt = max(1.0, min(3.0, timeout_seconds / 2))
    capture, frame, _transport = connect_rtsp(stream_url, per_attempt)
    if capture is None:
        return None
    try:
        return frame
    finally:
        capture.release()


def normalize_roi(rect, width: int, height: int) -> list[float] | None:
    x, y, w, h = [int(v) for v in rect]
    if width <= 0 or height <= 0 or w <= 0 or h <= 0:
        return None
    x = max(0, min(width - 1, x))
    y = max(0, min(height - 1, y))
    w = max(1, min(width - x, w))
    h = max(1, min(height - y, h))
    return [x / width, y / height, w / width, h / height]


def crop_normalized(frame, roi: list[float] | None):
    if frame is None or roi is None or len(roi) != 4:
        return frame
    height, width = frame.shape[:2]
    x, y, w, h = roi
    x1 = max(0, min(width - 1, int(round(x * width))))
    y1 = max(0, min(height - 1, int(round(y * height))))
    x2 = max(x1 + 1, min(width, int(round((x + w) * width))))
    y2 = max(y1 + 1, min(height, int(round((y + h) * height))))
    return frame[y1:y2, x1:x2]


def _write_detector_error(message: str) -> None:
    try:
        base = Path(os.getenv("APPDATA") or str(Path.home() / ".config")) / "久坐提醒"
        base.mkdir(parents=True, exist_ok=True)
        with (base / "detector-error.log").open("a", encoding="utf-8") as handle:
            handle.write(f"[{datetime.now().isoformat(timespec='seconds')}] {message}\n")
    except OSError:
        pass


class PresenceDebouncer:
    """Fail-safe human-presence debouncer.

    Start in 'present' so a transient detector miss can never immediately count
    as rest. Presence returns quickly; absence must persist for the configured
    grace period.
    """

    def __init__(self, absence_seconds: float, presence_seconds: float = 0.5) -> None:
        self.absence_seconds = max(1.0, float(absence_seconds))
        self.presence_seconds = max(0.0, float(presence_seconds))
        self.state = True
        self._absence_since: float | None = None
        self._presence_since: float | None = None

    def update(self, raw_present: bool, now: float) -> bool:
        if raw_present:
            self._absence_since = None
            if self.state:
                self._presence_since = None
                return True
            if self._presence_since is None:
                self._presence_since = now
            elif now - self._presence_since >= self.presence_seconds:
                self.state = True
                self._presence_since = None
            return self.state

        self._presence_since = None
        if not self.state:
            self._absence_since = None
            return False
        if self._absence_since is None:
            self._absence_since = now
        elif now - self._absence_since >= self.absence_seconds:
            self.state = False
            self._absence_since = None
        return self.state


class PresenceDetector:
    """Detect whether a human appears inside one or more configured regions."""

    def __init__(
        self,
        stream_url: str,
        interval: float,
        absence_grace: float,
        callback: Callable[[CameraStatus], None],
        roi: list[float] | None = None,
        rois: list[list[float]] | None = None,
        presence_grace: float = 1.0,
    ) -> None:
        self.stream_url = stream_url
        self.interval = max(0.5, float(interval))
        self.absence_grace = max(1.0, float(absence_grace))
        self.presence_grace = max(1.0, min(60.0, float(presence_grace)))
        self.callback = callback
        self.rois = [list(r) for r in (rois or ([] if roi is None else [roi]))]
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_reported_present: bool | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="rtsp-detector", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=6)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._run_person_presence()
                return
            except Exception as exc:
                _write_detector_error(f"{type(exc).__name__}: {exc}")
                self.callback(CameraStatus(False, False, f"识别线程异常：{type(exc).__name__}（详情已写入日志）"))
                if self._stop.wait(3):
                    return

    @staticmethod
    def _load_detectors(cv2):
        cascade_dir = getattr(cv2.data, "haarcascades", "")
        names = [
            ("正脸", "haarcascade_frontalface_default.xml"),
            ("正脸", "haarcascade_frontalface_alt2.xml"),
            ("侧脸", "haarcascade_profileface.xml"),
            ("上半身", "haarcascade_upperbody.xml"),
            ("全身", "haarcascade_fullbody.xml"),
        ]
        cascades = []
        for label, filename in names:
            try:
                classifier = cv2.CascadeClassifier(str(Path(cascade_dir) / filename))
                if not classifier.empty():
                    cascades.append((label, classifier))
            except Exception:
                continue

        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        return cascades, hog

    @staticmethod
    def _detect_in_region(cv2, sample, cascades, hog) -> str | None:
        if sample is None or sample.size == 0:
            return None

        h, w = sample.shape[:2]
        max_side = max(h, w)
        scale = 1.0
        if max_side < 480:
            scale = min(2.0, 480.0 / max(1, max_side))
        detect_img = cv2.resize(sample, None, fx=scale, fy=scale) if scale > 1.01 else sample
        gray = cv2.equalizeHist(cv2.cvtColor(detect_img, cv2.COLOR_BGR2GRAY))
        min_side = max(24, int(min(gray.shape[:2]) * 0.10))

        for label, classifier in cascades:
            try:
                detections = classifier.detectMultiScale(
                    gray,
                    scaleFactor=1.08,
                    minNeighbors=4,
                    minSize=(min_side, min_side),
                )
                if len(detections) > 0:
                    return label

                # Profile-face cascade is directional; try mirrored image too.
                if label == "侧脸":
                    detections = classifier.detectMultiScale(
                        cv2.flip(gray, 1),
                        scaleFactor=1.08,
                        minNeighbors=4,
                        minSize=(min_side, min_side),
                    )
                    if len(detections) > 0:
                        return label
            except cv2.error:
                continue

        try:
            rects, _weights = hog.detectMultiScale(
                detect_img,
                winStride=(8, 8),
                padding=(8, 8),
                scale=1.05,
            )
            if len(rects) > 0:
                return "人体"
        except cv2.error:
            pass
        return None

    def _run_person_presence(self) -> None:
        import cv2

        if not self.rois:
            self.callback(CameraStatus(False, False, "尚未设置人体检测区域"))
            return

        cascades, hog = self._load_detectors(cv2)
        if not cascades:
            self.callback(CameraStatus(False, False, "OpenCV 人体检测模型不可用"))
            return

        pending_frame = None

        while not self._stop.is_set():
            self.callback(CameraStatus(False, False, "正在连接网络摄像头…"))
            capture, first_frame, transport = connect_rtsp(self.stream_url, 3.0)
            if capture is None or first_frame is None:
                self.callback(CameraStatus(False, False, f"RTSP连接失败：{transport}，5秒后重试"))
                if self._stop.wait(5):
                    return
                continue

            # Reconnect conservatively: do not count any rest until absence has
            # been confirmed again after the stream is healthy.
            debouncer = PresenceDebouncer(self.absence_grace, self.presence_grace)
            self.callback(CameraStatus(False, True, f"视频已连接（{transport}），正在进行人体检测…"))
            failures = 0
            last_analysis = 0.0
            pending_frame = first_frame

            try:
                while not self._stop.is_set():
                    if pending_frame is not None:
                        frame = pending_frame
                        pending_frame = None
                        ok = True
                    else:
                        ok, frame = capture.read()

                    if not ok or frame is None:
                        failures += 1
                        if failures >= 5:
                            self.callback(CameraStatus(False, False, "视频流中断，正在重连"))
                            break
                        continue
                    failures = 0

                    now = time.monotonic()
                    if now - last_analysis < self.interval:
                        del frame
                        continue
                    last_analysis = now

                    labels: list[str] = []
                    for index, roi in enumerate(self.rois, start=1):
                        sample = crop_normalized(frame, roi)
                        label = self._detect_in_region(cv2, sample, cascades, hog)
                        if label:
                            labels.append(f"区域{index}:{label}")

                    raw_present = bool(labels)
                    present = debouncer.update(raw_present, now)

                    if present != self._last_reported_present:
                        _write_detector_error(
                            "人体检测状态切换 -> "
                            + ("在座" if present else "离座")
                            + " | "
                            + (", ".join(labels) if labels else "持续未检测到人体")
                        )
                        self._last_reported_present = present

                    if labels and not present:
                        detail = f"检测到人体，等待 {self.presence_grace:.0f} 秒有人确认"
                    elif labels:
                        detail = ", ".join(labels[:3])
                    elif present:
                        detail = f"暂未检测到人体，等待 {self.absence_grace:.0f} 秒无人确认"
                    else:
                        detail = "指定区域持续未检测到人体"

                    self.callback(CameraStatus(True, present, f"人体检测正常 · {detail}"))
                    del frame
            finally:
                capture.release()

            if not self._stop.is_set():
                self._stop.wait(2)
