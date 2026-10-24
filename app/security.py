import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from cryptography.fernet import Fernet
from . import config
from .db import db, connection_scope


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
    from .account_security import account, password_matches
    with db() as conn:
        return password_matches(account(conn), password)


def token_digest(token: str) -> str:
    return hmac.new(config.APP_SESSION_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()


def create_session(days: int = 30, conn=None):
    token = secrets.token_urlsafe(36)
    csrf = secrets.token_urlsafe(24)
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")
    digest = token_digest(token)
    with connection_scope(conn) as active:
        active.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.now(timezone.utc).isoformat(timespec='seconds'),))
        active.execute("INSERT INTO sessions(token_hash, csrf_token, expires_at) VALUES(?,?,?)", (digest, csrf, expires))
    return token, csrf, expires


def login_session(username, password, identity):
    """Password verification and session issuance cannot straddle a password reset."""
    from .account_security import account, ensure_account_schema, limit, password_matches
    if not configured():
        return None
    with db(immediate=True) as conn:
        ensure_account_schema(conn)
        if not limit(conn, 'login', identity, 30):
            return None
        valid = password_matches(account(conn), password)
        if not valid or username != config.APP_USERNAME:
            return None
        return create_session(conn=conn)


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
    if not session or not isinstance(csrf, str) or not csrf or not hmac.compare_digest(session["csrf_token"].encode(), csrf.encode()):
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
