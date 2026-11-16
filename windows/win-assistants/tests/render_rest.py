"""Real native lock-screen previews with isolated credentials and no camera."""
from pathlib import Path
import sys
from PIL import ImageGrab
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_sedentary_unlock import UnlockWindowTests
from sedentary.unlock import save_password
case=UnlockWindowTests()
case.setUp()
try:
    save_password("preview-only","preview-only")
    case.app.show_reminder()
    target=Path("dist/ui-preview")
    target.mkdir(parents=True,exist_ok=True)
    for name,complete in [("rest-elapsed",False),("rest-password",True)]:
        if complete: case.finish_rest()
        else:
            case.app.tracker.tick(False,1)
            case.app._update_lock_screen()
        case.root.after(250,case.root.quit)
        case.root.mainloop()
        window=case.app.reminder_window
        x,y=window.winfo_rootx(),window.winfo_rooty()
        ImageGrab.grab(bbox=(x,y,x+window.winfo_width(),y+window.winfo_height())).save(target/(name+".png"))
finally:
    case.tearDown()
