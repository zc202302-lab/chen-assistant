"""Render the real Tk UI without receivers or user configuration writes."""
from pathlib import Path
import sys
from PIL import ImageGrab

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
finally:
    case.tearDown()
