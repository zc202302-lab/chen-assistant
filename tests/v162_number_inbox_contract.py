from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-number-inbox-')
os.environ['APP_DB_PATH'] = str(Path(_TMPDIR.name) / 'app.db')
os.environ.setdefault('APP_USERNAME', 'number-inbox-test')
os.environ.setdefault('APP_PASSWORD_SALT', 'dGVzdHNhbHQ=')
os.environ.setdefault('APP_PASSWORD_HASH', 'x')
os.environ.setdefault('APP_SESSION_SECRET', 'number-inbox-session-secret')
os.environ.setdefault('APP_ENCRYPTION_KEY', 'x')
os.environ.setdefault('APP_SECURE_COOKIE', '0')

from fastapi.testclient import TestClient  # noqa: E402
from app.db import db, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.security import create_session  # noqa: E402
from app.v162_number_inbox import ensure_number_inbox_schema, TOKEN_META_KEY  # noqa: E402


def main():
    init_db()
    with db() as conn:
        token = ensure_number_inbox_schema(conn)
        assert len(token) >= 24
        saved = conn.execute('SELECT value FROM app_meta WHERE key=?', (TOKEN_META_KEY,)).fetchone()
        assert saved and saved['value'] == token

    client = TestClient(app)

    bad = client.get('/number-submit/not-the-token', follow_redirects=False)
    assert bad.status_code == 404, bad.text

    page = client.get(f'/number-submit/{token}')
    assert page.status_code == 200, page.text
    assert '请填写需要录入的号码' in page.text

    first = client.post(
        f'/number-submit/{token}',
        data={'number': '138 0013 8000', 'submitter': '测试同事', 'note': '首次提交'},
    )
    assert first.status_code == 200, first.text
    assert '提交成功' in first.text

    duplicate = client.post(
        f'/number-submit/{token}',
        data={'number': '+86 13800138000', 'submitter': '另一同事', 'note': '重复提交'},
    )
    assert duplicate.status_code == 200, duplicate.text
    assert '已经在待处理列表中' in duplicate.text

    with db() as conn:
        rows = conn.execute('SELECT * FROM number_inbox ORDER BY id').fetchall()
        assert len(rows) == 1, len(rows)
        assert rows[0]['normalized_number'] == '13800138000'
        assert rows[0]['status'] == 'pending'
        item_id = int(rows[0]['id'])

    unauthenticated = client.get('/work/number-inbox', follow_redirects=False)
    assert unauthenticated.status_code == 303, unauthenticated.status_code
    assert unauthenticated.headers['location'] == '/login'

    session_token, csrf, _ = create_session()
    client.cookies.set('session_token', session_token)
    admin = client.get('/work/number-inbox')
    assert admin.status_code == 200, admin.text
    assert '138 0013 8000' in admin.text
    assert '测试同事' in admin.text
    assert '1 个待录入' in client.get('/work').text

    done = client.post(
        f'/work/number-inbox/{item_id}/done',
        data={'csrf': csrf},
        follow_redirects=False,
    )
    assert done.status_code == 303
    with db() as conn:
        row = conn.execute('SELECT status,completed_at FROM number_inbox WHERE id=?', (item_id,)).fetchone()
        assert row['status'] == 'done'
        assert row['completed_at']

    reopened = client.post(
        f'/work/number-inbox/{item_id}/reopen',
        data={'csrf': csrf},
        follow_redirects=False,
    )
    assert reopened.status_code == 303
    with db() as conn:
        row = conn.execute('SELECT status,completed_at FROM number_inbox WHERE id=?', (item_id,)).fetchone()
        assert row['status'] == 'pending'
        assert row['completed_at'] == ''

    rotate = client.post(
        '/work/number-inbox/rotate-link',
        data={'csrf': csrf},
        follow_redirects=False,
    )
    assert rotate.status_code == 303
    with db() as conn:
        new_token = conn.execute('SELECT value FROM app_meta WHERE key=?', (TOKEN_META_KEY,)).fetchone()['value']
        assert new_token != token

    old_link = client.get(f'/number-submit/{token}', follow_redirects=False)
    assert old_link.status_code == 404
    new_link = client.get(f'/number-submit/{new_token}')
    assert new_link.status_code == 200

    print('v1.6.2 number inbox contract passed')


if __name__ == '__main__':
    main()
