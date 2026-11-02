"""Native local reminder editor, separate from connection credentials and Web Push."""
import tkinter as tk
from tkinter import ttk, messagebox
from .config import ReminderConfig
from .reminder_policy import validate_local_policy, effective_policy, allows


def show_reminder_settings(app):
    existing = getattr(app, 'reminder_settings_window', None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        return existing
    window = tk.Toplevel(app.root)
    app.reminder_settings_window = window
    window.title('本机提醒规则')
    window.geometry('580x630')
    window.configure(bg='#F4F6FA')
    window.resizable(False, False)
    frame = ttk.Frame(window, padding=16)
    frame.pack(fill='both', expand=True)
    actions = ttk.Frame(frame)
    actions.pack(side='bottom', fill='x', pady=(10, 0))
    cfg = app.config.reminders
    switches = {k: tk.BooleanVar(value=getattr(cfg, k)) for k in ('enabled', 'instant', 'scheduled')}
    ttk.Checkbutton(frame, text='本机提醒', variable=switches['enabled']).pack(anchor='w', pady=(0, 12))
    modes = ttk.LabelFrame(frame, text='提醒方式', padding=10, style='Reminder.TLabelframe')
    modes.pack(fill='x', pady=5)
    for key, label in [('instant', '即时提醒'), ('scheduled', '定时提醒')]:
        ttk.Checkbutton(modes, style='Reminder.TCheckbutton', text=label, variable=switches[key]).pack(side='left', padx=(0, 25))
    categories = {k: tk.BooleanVar(value=v) for k, v in cfg.categories.items()}
    group = ttk.LabelFrame(frame, text='通知类别', padding=10, style='Reminder.TLabelframe')
    group.pack(fill='x', pady=5)
    for key, label in [('number_inbox', '未加号码'), ('task', '待办'),
                       ('task_global', '全局待办'), ('task_customer', '客户待办')]:
        ttk.Checkbutton(group, style='Reminder.TCheckbutton', text=label, variable=categories[key]).pack(
            anchor='w', padx=(24 if key.startswith('task_') else 0, 0))
    timing = ttk.LabelFrame(frame, text='定时与重复 · 北京时间', padding=10, style='Reminder.TLabelframe')
    timing.pack(fill='x', pady=5)
    repeat = tk.StringVar(value='每天' if cfg.weekdays == list(range(7)) else '每周指定日期')
    selector = ttk.Combobox(timing, textvariable=repeat, values=['每天', '每周指定日期'], state='readonly', width=18, style='Reminder.TCombobox')
    selector.pack(anchor='w')
    day_frame = ttk.Frame(timing, style='Reminder.TFrame')
    day_frame.pack(fill='x', pady=8)
    days = [tk.BooleanVar(value=d in cfg.weekdays) for d in range(7)]
    day_buttons = []
    for d, label in enumerate(('一', '二', '三', '四', '五', '六', '日')):
        b = ttk.Checkbutton(day_frame, style='Reminder.TCheckbutton', text='周'+label, variable=days[d])
        b.pack(side='left', padx=(0, 6))
        day_buttons.append(b)
    def repeat_changed(_=None):
        for button in day_buttons:
            button.configure(state='disabled' if repeat.get() == '每天' else 'normal')
    selector.bind('<<ComboboxSelected>>', repeat_changed)
    repeat_changed()
    ttk.Label(timing, style='Reminder.TLabel', text='时间（空格分隔，最多12个）').pack(anchor='w', pady=(5, 3))
    times = tk.StringVar(value=' '.join(cfg.times))
    ttk.Entry(timing, textvariable=times).pack(fill='x')
    ttk.Label(frame, text='网页总开关关闭时，本机也暂停提醒。', style='Sub.TLabel').pack(anchor='w', pady=12)

    def save():
        raw = {k: v.get() for k, v in switches.items()}
        raw.update(times=times.get().split(), weekdays=list(range(7)) if repeat.get() == '每天'
                   else [d for d, v in enumerate(days) if v.get()],
                   categories={k: v.get() for k, v in categories.items()})
        try:
            candidate = ReminderConfig(**validate_local_policy(raw))
            old = app.config.reminders
            app.config.reminders = candidate
            try:
                app.config.save()
            except Exception:
                app.config.reminders = old
                raise
        except (ValueError, OSError) as exc:
            messagebox.showerror('提醒设置', str(exc), parent=window)
            return
        policy = effective_policy(candidate, getattr(app, 'number_reminder_policy', None))
        if not allows(policy, 'number_inbox'):
            app._hide_number_reminder_until_schedule()
        panel = app.todo_panel
        if hasattr(panel, 'last_payload'):
            panel.apply(panel.last_payload)
        window.destroy()
    ttk.Button(actions, text='取消', command=window.destroy).pack(side='right')
    ttk.Button(actions, text='保存', command=save, style='Accent.TButton').pack(side='right', padx=8)
    return window
