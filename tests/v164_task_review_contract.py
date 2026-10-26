from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-task-v164-')
os.environ['APP_DB_PATH'] = str(Path(_TMPDIR.name) / 'app.db')
os.environ.setdefault('APP_USERNAME', 'task-v164-test')
os.environ.setdefault('APP_PASSWORD_SALT', 'dGVzdHNhbHQ=')
os.environ.setdefault('APP_PASSWORD_HASH', 'x')
os.environ.setdefault('APP_SESSION_SECRET', 'task-v164-session-secret')
os.environ.setdefault('APP_ENCRYPTION_KEY', 'x')
os.environ.setdefault('APP_SECURE_COOKIE', '0')

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.db import db, init_db, now_iso  # noqa: E402
from app.main import app  # noqa: E402
from app.security import create_session  # noqa: E402
from app.v031_payment_workflow_routes import _set_initiated, ensure_v031  # noqa: E402


def main():
    init_db()
    with db() as conn:
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(tasks)').fetchall()}
        assert {'remind_at', 'is_payment_review', 'updated_at'} <= columns
        now = now_iso()
        cur = conn.execute(
            '''INSERT INTO customers(name,created_at,updated_at)
               VALUES(?,?,?)''',
            ('待办测试客户', now, now),
        )
        customer_id = int(cur.lastrowid)

    token, csrf, _ = create_session()
    client = TestClient(app)
    client.cookies.set('session_token', token)

    added = client.post(
        f'/customers/{customer_id}/tasks',
        data={
            'csrf': csrf,
            'title': '审核本月缴费名单',
            'remind_at': '2026-10-01T09:30',
            'note': '与同事二次确认',
            'is_payment_review': '1',
        },
        follow_redirects=False,
    )
    assert added.status_code == 303, added.text
    assert added.headers['location'].endswith('?tab=tasks')

    with db() as conn:
        row = conn.execute('SELECT * FROM tasks WHERE customer_id=?', (customer_id,)).fetchone()
        assert row is not None
        task_id = int(row['id'])
        assert row['title'] == '审核本月缴费名单'
        assert row['remind_at'] == '2026-10-01T09:30'
        assert row['remind_date'] == '2026-10-01'
        assert int(row['is_payment_review']) == 1

    edited = client.post(
        f'/tasks/{task_id}/edit',
        data={
            'csrf': csrf,
            'title': '审核并确认本月缴费名单',
            'remind_at': '2026-10-01T10:15',
            'note': '确认后才能发起缴费',
            'is_payment_review': '1',
        },
        follow_redirects=False,
    )
    assert edited.status_code == 303, edited.text
    with db() as conn:
        row = conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        assert row['title'] == '审核并确认本月缴费名单'
        assert row['remind_at'] == '2026-10-01T10:15'
        assert row['note'] == '确认后才能发起缴费'

        try:
            _set_initiated(
                conn,
                customer_id,
                '2026-10',
                {'id': 999, 'initiated': False, 'paid': False, 'notified': True},
            )
        except HTTPException as exc:
            assert exc.status_code == 409
            assert '请先确认缴费审核待办已完成' in str(exc.detail)
            assert '审核并确认本月缴费名单' in str(exc.detail)
        else:
            raise AssertionError('pending payment-review task did not block initiate')

        ensure_v031(conn)

        # The browser's centered acknowledgement explicitly unlocks only the
        # current initiate action; it does not silently complete or delete the task.
        _set_initiated(
            conn,
            customer_id,
            '2026-10',
            {'id': 999, 'initiated': False, 'paid': False, 'notified': True},
            review_confirmed=True,
        )

    toggled = client.post(
        f'/tasks/{task_id}/toggle',
        data={'csrf': csrf},
        follow_redirects=False,
    )
    assert toggled.status_code == 303
    with db() as conn:
        row = conn.execute('SELECT done FROM tasks WHERE id=?', (task_id,)).fetchone()
        assert int(row['done']) == 1

    second = client.post(
        f'/customers/{customer_id}/tasks',
        data={'csrf': csrf, 'title': '右上角直接办结测试'},
        follow_redirects=False,
    )
    assert second.status_code == 303
    with db() as conn:
        finish_id = int(conn.execute(
            'SELECT id FROM tasks WHERE customer_id=? AND title=?',
            (customer_id, '右上角直接办结测试'),
        ).fetchone()['id'])
    finished = client.post(
        f'/tasks/{finish_id}/toggle',
        data={'csrf': csrf, 'finish_delete': '1'},
        follow_redirects=False,
    )
    assert finished.status_code == 303
    with db() as conn:
        assert conn.execute('SELECT 1 FROM tasks WHERE id=?', (finish_id,)).fetchone() is None

    page = client.get(f'/customers/{customer_id}?tab=tasks')
    assert page.status_code == 200
    assert '缴费审核' in page.text
    assert '确认已审核' not in page.text  # completed tasks switch to restore
    assert '提醒时间' in page.text
    template = (ROOT / 'app/templates/customer_workspace_v029.html').read_text(encoding='utf-8')
    assert 'name="finish_delete" value="1"' in template
    assert '>办结<' in template

    print('v1.6.4 task review contract passed')


if __name__ == '__main__':
    main()
