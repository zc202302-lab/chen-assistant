"""Render the real Tk UI without receivers or user configuration writes."""
from pathlib import Path
import sys
from PIL import ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_navigation import NavigationTests

case = NavigationTests()
case.setUp()
try:
    target = Path("dist/ui-preview")
    target.mkdir(parents=True, exist_ok=True)
    for name, page in {**case.app.module_pages, "settings": case.app.settings_page}.items():
        case.app.navigation.select(page)
        case.root.after(180, case.root.quit)
        case.root.mainloop()
        case.root.update()
        x, y = case.root.winfo_rootx(), case.root.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + case.root.winfo_width(), y + case.root.winfo_height())).save(target / f"{name}.png")
    case.app.config.reminders.instant = False
    case.app._show_reminder_settings()
    dialog = case.app.reminder_settings_window
    dialog.lift()
    case.root.after(250, case.root.quit)
    case.root.mainloop()
    dialog.update()
    x, y = dialog.winfo_rootx(), dialog.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x+dialog.winfo_width(), y+dialog.winfo_height())).save(target / 'reminder-settings.png')
    from tkinter import ttk
    selector = next(w for w in case.descendants(dialog) if isinstance(w, ttk.Combobox))
    selector.set('每周指定日期')
    selector.event_generate('<<ComboboxSelected>>')
    for w in case.descendants(dialog):
        if isinstance(w, ttk.Checkbutton) and w.cget('text') in ('周二', '周四'):
            w.invoke()
    dialog.update()
    ImageGrab.grab(bbox=(x, y, x+dialog.winfo_width(), y+dialog.winfo_height())).save(target / 'reminder-weekly.png')
finally:
    case.tearDown()
