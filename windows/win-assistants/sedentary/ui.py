from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .camera import (
    CameraStatus,
    PresenceDetector,
    build_rtsp_url,
    capture_frame,
    normalize_roi,
    test_rtsp_connection,
)
from .control_bridge import consume_control_command, write_runtime_status
from .state import Phase, SedentaryTracker
from .startup import set_startup
from .shortcut import create_desktop_shortcut
from .storage import (
    DailyStats,
    Settings,
    log_event,
)
from .updater import cache_git_path, check_and_update, restart_app


BG = "#F4F7F6"
CARD = "#FFFFFF"
GREEN = "#167D68"
ORANGE = "#E67E22"
RED = "#B03A2E"
TEXT = "#18332E"
MUTED = "#61736F"


class SedentaryApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.embedded_mode = "--embedded" in sys.argv
        self.settings = Settings.load()
        self.daily_stats = DailyStats.load_today()
        self._last_stats_save = time.monotonic()
        self.tracker = SedentaryTracker(
            self.settings.work_minutes * 60,
            self.settings.break_minutes * 60,
        )
        self.camera_events: queue.Queue[CameraStatus] = queue.Queue(maxsize=2)
        self.detector: PresenceDetector | None = None
        self.last_tick = time.monotonic()
        self.camera_status = CameraStatus(False, False, "尚未配置RTSP摄像头")
        self.reminder_window: tk.Toplevel | None = None
        self.lock_countdown_label = None
        self.lock_state_label = None
        self.lock_progress: ttk.Progressbar | None = None
        self.tray_icon = None
        self._closing = False
        self._last_tested_signature: tuple | None = None

        self._configure_window()
        self._build_ui()
        self._saved_signature = self._settings_signature()
        self._start_detector()
        if not self.embedded_mode:
            self._start_tray()
        self.root.after(250, self._poll)

    def _configure_window(self) -> None:
        self.root.title("久坐提醒 · 局域网RTSP版")
        self.root.geometry("520x360")
        self.root.minsize(480, 320)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 22, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("Microsoft YaHei UI", 10))
        style.configure("Status.TLabel", background=CARD, foreground=GREEN, font=("Microsoft YaHei UI", 22, "bold"))
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("WorkTime.TLabel", background=CARD, foreground=MUTED, font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=7)
        style.configure("Accent.TButton", background=GREEN, foreground="white")

        outer = ttk.Frame(self.root, padding=28)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="久坐提醒", style="Title.TLabel").pack(anchor="center", pady=(30, 18))
        card = ttk.Frame(outer, style="Card.TFrame", padding=34)
        card.pack(fill="x", pady=(0, 16))
        self.status_label = ttk.Label(card, text="正在启动", style="Status.TLabel")
        self.status_label.pack(pady=(6, 12))
        self.detail_label = ttk.Label(card, text="正在检查配置…", style="Card.TLabel", wraplength=400, justify="center")
        self.detail_label.pack()
        self.work_time_label = ttk.Label(card, text="已工作 0 分钟", style="WorkTime.TLabel")
        self.work_time_label.pack(pady=(14, 0))
        ttk.Label(
            outer,
            text="关闭后可从 win-assistants 再次打开" if self.embedded_mode else "关闭窗口会自动隐藏到托盘",
            style="Sub.TLabel",
        ).pack(pady=(4, 0))

        self.host_var = tk.StringVar(value=self.settings.rtsp_host)
        self.port_var = tk.IntVar(value=self.settings.rtsp_port)
        self.path_var = tk.StringVar(value=self.settings.rtsp_path)
        self.username_var = tk.StringVar(value=self.settings.rtsp_username)
        self.password_var = tk.StringVar(value=self.settings.rtsp_password)
        self.work_var = tk.IntVar(value=self.settings.work_minutes)
        self.break_var = tk.IntVar(value=self.settings.break_minutes)
        self.grace_var = tk.IntVar(value=int(self.settings.absence_grace_seconds))
        self.startup_var = tk.BooleanVar(value=False if self.embedded_mode else self.settings.start_with_windows)
        self.roi_values = [list(roi) for roi in (self.settings.seat_rois or ([] if not self.settings.roi else [self.settings.roi]))]
        self.roi_value = list(self.roi_values[0]) if self.roi_values else None
        self.settings_window: tk.Toplevel | None = None
        self.test_button = None
        self.test_result = None

    def show_settings(self) -> None:
        if self.reminder_window and self.reminder_window.winfo_exists():
            self.reminder_window.bell()
            self.reminder_window.lift()
            return
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.deiconify()
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        self.settings_window = window
        window.title("久坐提醒 · 设置")
        window.geometry("590x760")
        window.minsize(520, 520)
        window.configure(bg=BG)
        window.protocol("WM_DELETE_WINDOW", window.withdraw)

        # Scrollable settings page: keeps the save button reachable on smaller screens.
        container = ttk.Frame(window)
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, bg=BG, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        outer = ttk.Frame(canvas, padding=20)
        canvas_window = canvas.create_window((0, 0), window=outer, anchor="nw")

        def _sync_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _sync_inner_width(event) -> None:
            canvas.itemconfigure(canvas_window, width=event.width)

        def _mousewheel(event) -> str:
            canvas.yview_scroll(int(-event.delta / 120), "units")
            return "break"

        outer.bind("<Configure>", _sync_scroll_region)
        canvas.bind("<Configure>", _sync_inner_width)
        window.bind("<MouseWheel>", _mousewheel)

        ttk.Label(outer, text="设置", style="Title.TLabel").pack(anchor="w", pady=(0, 12))

        camera_card = ttk.LabelFrame(outer, text=" 网络摄像头 ", padding=12)
        camera_card.pack(fill="x", pady=(0, 10))
        fields = [
            ("摄像头IP", self.host_var, False),
            ("RTSP端口", self.port_var, False),
            ("子码流路径", self.path_var, False),
            ("用户名", self.username_var, False),
            ("密码", self.password_var, True),
        ]
        for row, (label, variable, secret) in enumerate(fields):
            ttk.Label(camera_card, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(camera_card, textvariable=variable, show="●" if secret else "").grid(row=row, column=1, sticky="ew", padx=(12, 0), pady=3)
        camera_card.columnconfigure(1, weight=1)
        buttons = ttk.Frame(camera_card)
        buttons.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.test_button = ttk.Button(buttons, text="测试连接", command=self.test_connection)
        self.test_button.pack(side="right")
        self.test_result = ttk.Label(camera_card, text="修改摄像头参数后请先测试连接", foreground=MUTED)
        self.test_result.grid(row=6, column=0, columnspan=2, sticky="w", pady=(7, 0))

        detection_card = ttk.LabelFrame(outer, text=" 人体区域检测 ", padding=12)
        detection_card.pack(fill="x", pady=(0, 10))
        ttk.Label(
            detection_card,
            text="只判断指定区域内是否检测到人，不再区分坐姿，也不需要空座校准。",
            foreground=MUTED,
            wraplength=500,
        ).pack(anchor="w")

        detect_buttons = ttk.Frame(detection_card)
        detect_buttons.pack(fill="x", pady=(8, 0))
        self.roi_button = ttk.Button(detect_buttons, text="新增检测区域", command=self.set_detection_roi)
        self.roi_button.pack(side="left")
        self.clear_roi_button = ttk.Button(detect_buttons, text="清空检测区域", command=self.clear_detection_rois)
        self.clear_roi_button.pack(side="left", padx=(8, 0))
        self.roi_status = ttk.Label(detection_card, text="", foreground=MUTED)
        self.roi_status.pack(anchor="w", pady=(7, 0))
        self._refresh_roi_status()
        ttk.Label(
            detection_card,
            text="可框 1～5 个区域；区域内检测到正脸、侧脸、上半身或整个人体任一特征即视为工作中。",
            foreground=MUTED,
            wraplength=500,
        ).pack(anchor="w", pady=(4, 0))
        self._refresh_detection_controls()

        settings_card = ttk.LabelFrame(outer, text=" 提醒规则 ", padding=12)
        settings_card.pack(fill="x")
        rules = [
            ("久坐阈值（分钟）", self.work_var, 1, 120),
            ("有效休息（分钟）", self.break_var, 1, 60),
            ("无人确认（秒）", self.grace_var, 1, 60),
        ]
        for row, (label, variable, minimum, maximum) in enumerate(rules):
            ttk.Label(settings_card, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Spinbox(settings_card, from_=minimum, to=maximum, textvariable=variable, width=8).grid(row=row, column=1, sticky="e", pady=3)
        settings_card.columnconfigure(0, weight=1)
        next_row = len(rules)
        startup_check = ttk.Checkbutton(
            settings_card,
            text="由 win-assistants 统一管理开机启动" if self.embedded_mode else "随Windows登录自动启动（静默进入托盘）",
            variable=self.startup_var,
        )
        startup_check.grid(row=next_row, column=0, columnspan=2, sticky="w", pady=(7, 3))
        if self.embedded_mode:
            startup_check.state(["disabled"])
        ttk.Button(settings_card, text="保存全部设置", style="Accent.TButton", command=self.save_settings).grid(row=next_row + 1, column=0, columnspan=2, sticky="ew", pady=(7, 0))

        update_card = ttk.LabelFrame(outer, text=" 程序与启动 ", padding=12)
        update_card.pack(fill="x", pady=(10, 0))
        if self.embedded_mode:
            ttk.Label(
                update_card,
                text="久坐功能已内置到 win-assistants；开机启动和程序更新请在主界面统一管理。",
                wraplength=500,
            ).pack(anchor="w")
        else:
            ttk.Label(update_card, text="可在软件内更新，也可创建桌面快捷方式直接启动。").pack(anchor="w")
            update_buttons = ttk.Frame(update_card)
            update_buttons.pack(fill="x", pady=(8, 0))
            ttk.Button(update_buttons, text="创建桌面快捷方式", command=self.create_shortcut_from_ui).pack(side="left")
            ttk.Button(update_buttons, text="检查更新", command=self.check_updates_from_ui).pack(side="right")

        ttk.Label(
            outer,
            text=f"版本 {__version__} · 检测区域内有人即工作中；持续无人达到“无人确认”时间后开始休息。",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(12, 0))

    def _current_connection(self) -> tuple[str, int, str, str, str] | None:
        host = self.host_var.get().strip()
        path = self.path_var.get().strip()
        username = self.username_var.get().strip()
        password = self.password_var.get()
        if not host or "://" in host or any(char.isspace() for char in host):
            return None
        try:
            port = int(self.port_var.get())
        except (tk.TclError, ValueError):
            return None
        if not 1 <= port <= 65535 or not path:
            return None
        return host, port, path, username, password

    def _settings_signature(self) -> tuple:
        connection = self._current_connection()
        return connection if connection is not None else ()

    def _stream_url(self) -> str | None:
        connection = self._current_connection()
        return build_rtsp_url(*connection) if connection else None

    def test_connection(self) -> None:
        url = self._stream_url()
        if not url:
            messagebox.showerror("参数不完整", "请填写正确的摄像头IP、端口和子码流路径。")
            return
        signature = self._settings_signature()
        if self.test_button:
            self.test_button.configure(text="测试中…", state="disabled")
        if self.test_result:
            self.test_result.configure(text="正在读取视频帧，最长约8秒…", foreground=ORANGE)

        def worker() -> None:
            try:
                if self.detector:
                    self.detector.stop()
                ok, message = test_rtsp_connection(url)
            except Exception as exc:
                ok, message = False, f"测试失败：{type(exc).__name__}"
            self.root.after(0, lambda: self._finish_connection_test(ok, message, signature))

        threading.Thread(target=worker, name="rtsp-test", daemon=True).start()

    def _finish_connection_test(self, ok: bool, message: str, signature: tuple) -> None:
        if self.test_button:
            self.test_button.configure(text="测试连接", state="normal")
        if self.test_result:
            self.test_result.configure(text=message, foreground=GREEN if ok else RED)
        self._last_tested_signature = signature if ok else None
        self._start_detector()

    def _refresh_detection_controls(self) -> None:
        return

    def set_detection_roi(self) -> None:
        url = self._stream_url()
        if not url:
            messagebox.showerror("参数不完整", "请先填写正确的摄像头参数。")
            return
        messagebox.showinfo(
            "新增检测区域",
            "稍后会弹出摄像头画面。请直接框住“只要你在工作时，人会出现”的区域，然后按 Enter 或空格确认；按 Esc 取消。\n\n"
            "程序以后只判断这个区域里有没有人，不再做空座或坐姿校准。可添加 1～5 个区域，尽量不要把你站立休息的位置框进去。",
        )

        def worker() -> None:
            try:
                if self.detector:
                    self.detector.stop()
                import cv2
                frame = capture_frame(url, 8.0)
                if frame is None:
                    self.root.after(0, lambda: messagebox.showerror("读取失败", "未能读取摄像头画面。"))
                    return
                if frame.shape[1] > 960:
                    scale = 960 / frame.shape[1]
                    frame = cv2.resize(frame, (960, int(frame.shape[0] * scale)))
                rect = cv2.selectROI("Chen Sit Guard - Select ROI", frame, showCrosshair=True, fromCenter=False)
                cv2.destroyWindow("Chen Sit Guard - Select ROI")
                roi = normalize_roi(rect, frame.shape[1], frame.shape[0])
                if roi is None:
                    return
                self.root.after(0, lambda: self._apply_roi(roi))
            except Exception as exc:
                error_text = str(exc)
                self.root.after(0, lambda text=error_text: messagebox.showerror("设置失败", text))
            finally:
                self.root.after(0, self._start_detector)

        threading.Thread(target=worker, name="roi-selector", daemon=True).start()

    def _apply_roi(self, roi: list[float]) -> None:
        if len(self.roi_values) >= 5:
            messagebox.showinfo("区域已满", "最多保存 5 个检测区域。")
            return
        self.roi_values.append(list(roi))
        self.roi_value = list(self.roi_values[0])
        self._refresh_roi_status()
        messagebox.showinfo(
            "检测区域已添加",
            f"当前共有 {len(self.roi_values)} 个检测区域。\n\n"
            "如果一个区域无法覆盖你所有工作姿势，可以继续添加。完成后点击“保存全部设置”即可。",
        )

    def _refresh_roi_status(self) -> None:
        if hasattr(self, "roi_status"):
            self.roi_status.configure(text=f"检测区域：{len(self.roi_values)} / 5")

    def clear_detection_rois(self) -> None:
        if not self.roi_values:
            return
        if not messagebox.askyesno("清空检测区域", "确定清空全部检测区域吗？"):
            return
        self.roi_values = []
        self.roi_value = None
        self._refresh_roi_status()

    def _start_detector(self) -> None:
        try:
            self.daily_stats.save()
        except OSError:
            pass
        if self.detector:
            self.detector.stop()
            self.detector = None
        url = build_rtsp_url(
            self.settings.rtsp_host,
            self.settings.rtsp_port,
            self.settings.rtsp_path,
            self.settings.rtsp_username,
            self.settings.rtsp_password,
        ) if self.settings.rtsp_host else None
        if not url:
            self.camera_status = CameraStatus(False, False, "请先配置并测试RTSP摄像头")
            return
        self.camera_status = CameraStatus(False, False, "正在连接网络摄像头…")
        self.detector = PresenceDetector(
            url,
            self.settings.sample_interval_seconds,
            self.settings.absence_grace_seconds,
            self._camera_callback,
            roi=self.settings.roi,
            rois=self.settings.seat_rois or self.roi_values,
        )
        self.detector.start()

    def _camera_callback(self, status: CameraStatus) -> None:
        try:
            while self.camera_events.full():
                self.camera_events.get_nowait()
            self.camera_events.put_nowait(status)
        except (queue.Empty, queue.Full):
            pass

    def _poll(self) -> None:
        if self._closing:
            return
        try:
            while True:
                self.camera_status = self.camera_events.get_nowait()
        except queue.Empty:
            pass
        now = time.monotonic()
        elapsed = now - self.last_tick
        self.last_tick = now

        today = date.today().isoformat()
        if self.daily_stats.date != today:
            try:
                self.daily_stats.save()
            except OSError:
                pass
            self.daily_stats = DailyStats(date=today)
            self._last_stats_save = now

        if self.camera_status.available:
            self.daily_stats.add_sample(self.camera_status.present, elapsed)
            update = self.tracker.tick(self.camera_status.present, elapsed)
            if update.reminder_due:
                self.daily_stats.reminder_count += 1
                log_event("久坐提醒", update.work_seconds)
                self.show_reminder()
            if update.break_completed:
                self.daily_stats.completed_break_count += 1
                log_event("完成有效休息", self.settings.break_minutes * 60)
                if self.reminder_window and self.reminder_window.winfo_exists():
                    self.close_reminder()
            if time.monotonic() - self._last_stats_save >= 10:
                self.daily_stats.save()
                self._last_stats_save = time.monotonic()
        self._refresh_labels()
        self._publish_runtime_status()
        self._consume_external_command()
        self.root.after(250, self._poll)

    def _publish_runtime_status(self) -> None:
        snap = self.tracker.snapshot()
        if not self.camera_status.available:
            title = "检测异常"
        elif snap.phase == Phase.REMINDING:
            title = "工作中" if self.camera_status.present else "已休息"
        else:
            title = "工作中" if self.camera_status.present else "已休息"
        try:
            write_runtime_status(
                {
                    "version": __version__,
                    "status": title,
                    "detail": self.camera_status.message,
                    "available": bool(self.camera_status.available),
                    "present": bool(self.camera_status.present),
                    "reminder_active": bool(self.tracker.reminder_active),
                    "work_seconds": round(max(0.0, snap.work_seconds), 1),
                    "away_seconds": round(max(0.0, snap.away_seconds), 1),
                    "remaining_break_seconds": round(max(0.0, snap.remaining_break_seconds), 1),
                    "work_limit_minutes": int(self.settings.work_minutes),
                    "break_minutes": int(self.settings.break_minutes),
                }
            )
        except OSError:
            pass

    def _consume_external_command(self) -> None:
        try:
            command = consume_control_command()
        except OSError:
            return
        if not command:
            return
        action = command.get("action")
        if action == "show_status":
            self.show_window()
        elif action == "show_settings":
            self.show_settings()
        elif action == "check_update":
            self.check_updates_from_ui()

    def _refresh_labels(self) -> None:
        snap = self.tracker.snapshot()
        if not self.camera_status.available:
            title, detail, color = "检测异常", self.camera_status.message, RED
        elif snap.phase == Phase.REMINDING:
            if self.camera_status.present:
                title, detail, color = "工作中", self.camera_status.message, ORANGE
            else:
                title, detail, color = "已休息", self.camera_status.message, GREEN
        elif self.camera_status.present:
            title, detail, color = "工作中", self.camera_status.message, GREEN
        else:
            title, detail, color = "已休息", self.camera_status.message, GREEN
        self.status_label.configure(text=title, foreground=color)
        self.detail_label.configure(text=detail)
        worked_minutes = int(max(0.0, snap.work_seconds) // 60)
        self.work_time_label.configure(text=f"已工作 {worked_minutes} 分钟")

    def save_settings(self) -> None:
        connection = self._current_connection()
        if connection is None:
            messagebox.showerror("参数不完整", "请填写正确的摄像头IP、端口和子码流路径。")
            return
        signature = self._settings_signature()
        if signature != self._saved_signature and signature != self._last_tested_signature:
            messagebox.showwarning("请先测试", "摄像头参数发生了变化，请先点击“测试连接”。")
            return
        try:
            work = max(1, min(120, int(self.work_var.get())))
            rest = max(1, min(60, int(self.break_var.get())))
            grace = max(1, min(60, int(self.grace_var.get())))
        except (tk.TclError, ValueError):
            messagebox.showerror("设置有误", "提醒规则必须是有效整数。")
            return
        host, port, path, username, password = connection
        if not self.roi_values:
            messagebox.showwarning("缺少检测区域", "请至少添加 1 个检测区域。")
            return
        restart_camera = (
            signature != self._saved_signature
            or grace != int(self.settings.absence_grace_seconds)
            or self.roi_values != (self.settings.seat_rois or ([] if not self.settings.roi else [self.settings.roi]))
        )
        self.settings.rtsp_host = host
        self.settings.rtsp_port = port
        self.settings.rtsp_path = path
        self.settings.rtsp_username = username
        self.settings.rtsp_password = password
        self.settings.work_minutes = work
        self.settings.break_minutes = rest
        self.settings.absence_grace_seconds = float(grace)
        self.settings.start_with_windows = False if self.embedded_mode else bool(self.startup_var.get())
        self.settings.seat_rois = [list(roi) for roi in self.roi_values]
        self.settings.roi = list(self.roi_values[0]) if self.roi_values else None
        try:
            self.settings.save()
            if not self.embedded_mode:
                set_startup(self.settings.start_with_windows)
        except (OSError, RuntimeError) as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        self._saved_signature = signature
        self.tracker.configure(work * 60, rest * 60)
        if restart_camera:
            self._start_detector()
        messagebox.showinfo("已保存", "设置已经生效。")

    def show_reminder(self) -> None:
        if self.reminder_window and self.reminder_window.winfo_exists():
            self.reminder_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.reminder_window = window
        window.title("强制休息")
        window.configure(bg="#0B1F1A")
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.protocol("WM_DELETE_WINDOW", lambda: None)
        window.bind("<Escape>", lambda event: "break")
        window.bind("<Alt-F4>", lambda event: "break")

        if sys.platform == "win32":
            import ctypes
            x = ctypes.windll.user32.GetSystemMetrics(76)
            y = ctypes.windll.user32.GetSystemMetrics(77)
            width = ctypes.windll.user32.GetSystemMetrics(78)
            height = ctypes.windll.user32.GetSystemMetrics(79)
        else:
            x, y = 0, 0
            width, height = window.winfo_screenwidth(), window.winfo_screenheight()
        window.geometry(f"{width}x{height}{x:+d}{y:+d}")

        content = tk.Frame(window, bg="#0B1F1A")
        content.place(relx=0.5, rely=0.5, anchor="center")

        self.lock_countdown_label = tk.Label(
            content,
            text="00:00",
            bg="#0B1F1A",
            fg="#FFFFFF",
            font=("Microsoft YaHei UI", 72, "bold"),
        )
        self.lock_countdown_label.pack()
        self.lock_state_label = tk.Label(
            content,
            text="",
            bg="#0B1F1A",
            fg="#9CB7B0",
            font=("Microsoft YaHei UI", 12),
        )
        self.lock_state_label.pack(pady=(18, 0))

        test_close = tk.Button(
            window,
            text="测试关闭",
            command=self.test_close_reminder,
            bg="#16352E",
            fg="#9CB7B0",
            activebackground="#20483F",
            activeforeground="white",
            relief="flat",
            bd=0,
            font=("Microsoft YaHei UI", 10),
            padx=14,
            pady=7,
            cursor="hand2",
        )
        test_close.place(relx=0.985, rely=0.975, anchor="se")

        try:
            window.grab_set_global()
        except tk.TclError:
            window.grab_set()
        window.bell()
        window.focus_force()
        self._update_lock_screen()
        self._enforce_lock_focus()

    @staticmethod
    def _format_mmss(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        minutes, secs = divmod(total, 60)
        return f"{minutes:02d}:{secs:02d}"

    def _update_lock_screen(self) -> None:
        if not self.reminder_window or not self.reminder_window.winfo_exists():
            return
        if not self.tracker.reminder_active:
            self.close_reminder()
            return

        snap = self.tracker.snapshot()
        completed = min(snap.away_seconds, self.tracker.break_seconds)

        if self.lock_countdown_label and self.lock_countdown_label.winfo_exists():
            self.lock_countdown_label.configure(text=self._format_mmss(completed))
        if self.lock_state_label and self.lock_state_label.winfo_exists():
            if not self.camera_status.available:
                state_text = "检测异常，休息计时暂停"
            elif self.camera_status.present:
                state_text = "检测到人体 · 休息计时暂停"
            else:
                state_text = "区域无人 · 正在累计休息"
            self.lock_state_label.configure(text=state_text)

        self.reminder_window.after(250, self._update_lock_screen)

    def _enforce_lock_focus(self) -> None:
        if not self.reminder_window or not self.reminder_window.winfo_exists():
            return
        self.reminder_window.attributes("-topmost", True)
        self.reminder_window.lift()
        self.reminder_window.focus_force()
        self.reminder_window.after(1000, self._enforce_lock_focus)

    def test_close_reminder(self) -> None:
        """Temporary escape hatch while detection is under active testing."""
        if not self.reminder_window or not self.reminder_window.winfo_exists():
            return
        log_event("测试关闭强制休息", self.tracker.snapshot().away_seconds)
        self.tracker.reset_cycle(present=self.camera_status.present if self.camera_status.available else True)
        self.close_reminder()

    def close_reminder(self) -> None:
        if self.reminder_window and self.reminder_window.winfo_exists():
            try:
                self.reminder_window.grab_release()
            except tk.TclError:
                pass
            self.reminder_window.destroy()
        self.reminder_window = None
        self.lock_countdown_label = None
        self.lock_state_label = None

    def show_window(self) -> None:
        self.root.after(0, self._show_window_ui)

    def _show_window_ui(self) -> None:
        if self.reminder_window and self.reminder_window.winfo_exists():
            self.reminder_window.bell()
            self.reminder_window.lift()
            self.reminder_window.focus_force()
            return
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self) -> None:
        self.root.withdraw()

    def _start_tray(self) -> None:
        try:
            from PIL import Image, ImageDraw
            import pystray
            image = Image.new("RGB", (64, 64), GREEN)
            draw = ImageDraw.Draw(image)
            draw.ellipse((17, 8, 47, 38), fill="white")
            draw.rectangle((27, 34, 37, 57), fill="white")
            menu = pystray.Menu(
                pystray.MenuItem("打开状态", lambda: self.show_window(), default=True),
                pystray.MenuItem("设置", lambda: self.root.after(0, self.show_settings)),
                pystray.MenuItem("检查更新", lambda: self.root.after(0, self.check_updates_from_ui)),
                pystray.MenuItem("退出", lambda: self.root.after(0, self.request_quit)),
            )
            self.tray_icon = pystray.Icon("sedentary-reminder", image, "久坐提醒", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception:
            self.tray_icon = None

    def create_shortcut_from_ui(self) -> None:
        ok, message = create_desktop_shortcut()
        if ok:
            messagebox.showinfo("桌面快捷方式", message + "\n\n以后双击桌面上的“晨·久坐守护”即可启动，不会弹出 CMD 黑窗口。")
        else:
            messagebox.showerror("桌面快捷方式", message)

    def check_updates_from_ui(self) -> None:
        if self.embedded_mode:
            messagebox.showinfo("检查更新", "久坐功能已内置到 win-assistants，请在主界面使用“检查更新”。")
            return
        if self.reminder_window and self.reminder_window.winfo_exists():
            self.reminder_window.bell()
            messagebox.showwarning("强制休息中", "强制休息完成后才能更新程序。")
            return

        def worker() -> None:
            status, message = check_and_update()
            self.root.after(0, lambda: self._finish_update_check(status, message))

        threading.Thread(target=worker, name="app-updater", daemon=True).start()

    def _finish_update_check(self, status: str, message: str) -> None:
        if status == "updated":
            try:
                self.daily_stats.save()
            except OSError:
                pass

            if self.detector:
                self.detector.stop()

            ok, restart_message = restart_app()
            if not ok:
                messagebox.showerror(
                    "更新完成但重启失败",
                    message + "\n\n" + restart_message + "\n\n当前程序会继续保持打开。",
                )
                self._start_detector()
                return

            messagebox.showinfo("更新完成", message + "\n\n" + restart_message)
            if self.tray_icon:
                self.tray_icon.stop()
            self._closing = True
            self.root.destroy()
            return
        if status == "git_missing":
            path = filedialog.askopenfilename(
                title="选择 Git 程序（只需一次）",
                filetypes=[("Git executable", "git.exe"), ("Executable", "*.exe"), ("All files", "*.*")],
            )
            if not path:
                messagebox.showwarning("检查更新", "未选择 Git，更新未执行。")
                return
            ok, detail = cache_git_path(path)
            if not ok:
                messagebox.showerror("Git 路径无效", detail)
                return

            def retry_worker() -> None:
                retry_status, retry_message = check_and_update()
                self.root.after(0, lambda: self._finish_update_check(retry_status, retry_message))

            threading.Thread(target=retry_worker, name="app-updater-retry", daemon=True).start()
            return

        if status == "current":
            messagebox.showinfo("检查更新", message)
        elif status == "offline":
            messagebox.showwarning("检查更新", message)
        else:
            messagebox.showerror("检查更新", message)

    def request_quit(self) -> None:
        if self.reminder_window and self.reminder_window.winfo_exists():
            self.reminder_window.bell()
            return
        self.quit()

    def quit(self) -> None:
        self._closing = True
        try:
            self.daily_stats.save()
        except OSError:
            pass
        if self.detector:
            self.detector.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.destroy()


def _acquire_single_instance():
    if sys.platform != "win32":
        return None, True
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\ChenSitGuard")
    already_exists = kernel32.GetLastError() == 183
    if already_exists:
        if handle:
            kernel32.CloseHandle(handle)
        return None, False
    return handle, True


def run() -> None:
    mutex_handle, acquired = _acquire_single_instance()
    if not acquired:
        return
    root = tk.Tk()
    app = SedentaryApp(root)
    if "--startup" in sys.argv:
        root.withdraw()
    try:
        root.mainloop()
    finally:
        if not app._closing:
            app.quit()
        if mutex_handle and sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(mutex_handle)
            except Exception:
                pass
