from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-stability-')
os.environ['APP_DB_PATH'] = str(Path(_TMPDIR.name) / 'app.db')
os.environ.setdefault('APP_USERNAME', 'stability-test')
os.environ.setdefault('APP_PASSWORD_SALT', 'dGVzdHNhbHQ=')
os.environ.setdefault('APP_PASSWORD_HASH', 'x')
os.environ.setdefault('APP_SESSION_SECRET', 'stability-test-session')
os.environ.setdefault('APP_ENCRYPTION_KEY', 'x')
os.environ.setdefault('APP_SECURE_COOKIE', '0')

from app import config  # noqa: E402
from app.db import connect, init_db  # noqa: E402
from app.main import app  # noqa: E402


def main():
    # One source of truth for version reporting. This specifically guards against
    # production deploys being rejected after restart because /health lagged behind.
    assert app.version == config.APP_VERSION, (app.version, config.APP_VERSION)
    health_routes = [
        route for route in app.router.routes
        if getattr(route, 'path', '') == '/health' and 'GET' in getattr(route, 'methods', set())
    ]
    assert len(health_routes) == 1, len(health_routes)
    health_payload = health_routes[0].endpoint()
    assert health_payload.get('ok') is True, health_payload
    assert health_payload.get('version') == config.APP_VERSION, health_payload

    # Validate the actual connection factory, not just source text. Short bursts of
    # browser writes should wait for SQLite's writer lock instead of failing fast.
    init_db()
    conn = connect()
    try:
        assert int(conn.execute('PRAGMA foreign_keys').fetchone()[0]) == 1
        assert int(conn.execute('PRAGMA busy_timeout').fetchone()[0]) >= 30000
        assert str(conn.execute('PRAGMA journal_mode').fetchone()[0]).lower() == 'wal'
        assert str(conn.execute('PRAGMA synchronous').fetchone()[0]).upper() in {'1', 'NORMAL'}
        assert conn.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        conn.close()

    print('stability contract passed: version/health + SQLite safety')


if __name__ == '__main__':
    main()
