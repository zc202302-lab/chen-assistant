import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from cryptography.fernet import Fernet
from . import config
from .db import db


def configured() -> bool:
    return all([
        config.APP_PASSWORD_SALT,
        config.APP_PASSWORD_HASH,
        config.APP_SESSION_SECRET,
        config.APP_ENCRYPTION_KEY,
    ])


def password_hash(password: str, salt_b64: str) -> str:
    salt = base64.urlsafe_b64decode(salt_b64.encode())
    raw = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return base64.urlsafe_b64encode(raw).decode()


def verify_login(username: str, password: str) -> bool:
    if not configured() or username != config.APP_USERNAME:
        return False
    got = password_hash(password, config.APP_PASSWORD_SALT)
    return hmac.compare_digest(got, config.APP_PASSWORD_HASH)


def token_digest(token: str) -> str:
    return hmac.new(config.APP_SESSION_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()


def create_session(days: int = 30):
    token = secrets.token_urlsafe(36)
    csrf = secrets.token_urlsafe(24)
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")
    digest = token_digest(token)
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.now(timezone.utc).isoformat(timespec='seconds'),))
        conn.execute("INSERT INTO sessions(token_hash, csrf_token, expires_at) VALUES(?,?,?)", (digest, csrf, expires))
    return token, csrf, expires


def get_session(token: str | None):
    if not token or not configured():
        return None
    digest = token_digest(token)
    with db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE token_hash=?", (digest,)).fetchone()
        if not row:
            return None
        if row["expires_at"] < datetime.now(timezone.utc).isoformat(timespec="seconds"):
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (digest,))
            return None
        return dict(row)


def delete_session(token: str | None):
    if not token or not configured():
        return
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_digest(token),))


def require_csrf(session: dict, csrf: str):
    if not session or not csrf or not hmac.compare_digest(session["csrf_token"], csrf):
        raise ValueError("CSRF校验失败")


def fernet():
    if not config.APP_ENCRYPTION_KEY:
        raise RuntimeError("APP_ENCRYPTION_KEY 未配置")
    return Fernet(config.APP_ENCRYPTION_KEY.encode())


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    return fernet().decrypt(value.encode("utf-8")).decode("utf-8")
