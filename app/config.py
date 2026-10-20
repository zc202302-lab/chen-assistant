from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
APP_VERSION = "1.7.21"


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

# Tests and local tooling may explicitly point at an isolated SQLite database.
# Production leaves APP_DB_PATH unset and continues to use data/app.db.
_db_override = os.getenv("APP_DB_PATH", "").strip()
DB_PATH = Path(_db_override).expanduser() if _db_override else ROOT / "data" / "app.db"
DATA_DIR = DB_PATH.parent

APP_USERNAME = os.getenv("APP_USERNAME", "晨")
APP_PASSWORD_SALT = os.getenv("APP_PASSWORD_SALT", "")
APP_PASSWORD_HASH = os.getenv("APP_PASSWORD_HASH", "")
APP_SESSION_SECRET = os.getenv("APP_SESSION_SECRET", "")
APP_ENCRYPTION_KEY = os.getenv("APP_ENCRYPTION_KEY", "")
APP_SECURE_COOKIE = os.getenv("APP_SECURE_COOKIE", "1") == "1"
APP_BASE_URL = os.getenv("APP_BASE_URL", "")

# v1.3 customer documents. In production this normally points to a localhost port
# forwarded over the encrypted Qingdao -> RackNerd SSH tunnel; the file service on
# the US host itself binds to 127.0.0.1 and is never exposed to the public Internet.
REMOTE_STORAGE_BASE_URL = os.getenv("REMOTE_STORAGE_BASE_URL", "").strip()
REMOTE_STORAGE_TOKEN = os.getenv("REMOTE_STORAGE_TOKEN", "").strip()
try:
    REMOTE_STORAGE_MAX_FILE_MB = max(1, min(500, int(os.getenv("REMOTE_STORAGE_MAX_FILE_MB", "50"))))
except ValueError:
    REMOTE_STORAGE_MAX_FILE_MB = 50



