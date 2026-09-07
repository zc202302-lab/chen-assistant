from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "app.db"
ENV_PATH = ROOT / ".env"


def load_env(path: Path = ENV_PATH):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


load_env()

APP_USERNAME = os.getenv("APP_USERNAME", "晨")
APP_PASSWORD_SALT = os.getenv("APP_PASSWORD_SALT", "")
APP_PASSWORD_HASH = os.getenv("APP_PASSWORD_HASH", "")
APP_SESSION_SECRET = os.getenv("APP_SESSION_SECRET", "")
APP_ENCRYPTION_KEY = os.getenv("APP_ENCRYPTION_KEY", "")
APP_SECURE_COOKIE = os.getenv("APP_SECURE_COOKIE", "1") == "1"
APP_BASE_URL = os.getenv("APP_BASE_URL", "")
