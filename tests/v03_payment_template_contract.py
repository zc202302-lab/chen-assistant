from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v03-payment-template-contract-')
os.environ['APP_DB_PATH'] = str(Path(_TMPDIR.name) / 'app.db')

from fastapi import HTTPException  # noqa: E402
from app.db import db, init_db, now_iso  # noqa: E402
from app.v03_mail_draft_routes import (  # noqa: E402
    _attachment_filename,
    _ensure_mail_templates,
    _get_template,
    _save_template,
)


def main():
    init_db()
    now = now_iso()
    with db() as conn:
        cid = int(conn.execute(
            'INSERT INTO customers(name,created_at,updated_at) VALUES(?,?,?)',
            ('模板测试客户', now, now),
        ).lastrowid)

        # Simulate the old v0.3 table so production migration is covered.
        conn.execute('DROP TABLE IF EXISTS customer_mail_templates_v03')
        conn.execute(
            '''CREATE TABLE customer_mail_templates_v03 (
                   customer_id INTEGER PRIMARY KEY REFERENCES customers(id) ON DELETE CASCADE,
                   subject TEXT NOT NULL DEFAULT '',
                   body TEXT NOT NULL DEFAULT '',
                   updated_at TEXT NOT NULL DEFAULT ''
               )'''
        )
        _ensure_mail_templates(conn)
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(customer_mail_templates_v03)')}
        assert 'attachment_filename' in columns

        saved = _save_template(conn, cid, '长期主题', '长期正文', '本客户缴费清单')
        assert saved['attachment_filename'] == '本客户缴费清单.txt'
        loaded = _get_template(conn, cid)
        assert loaded['subject'] == '长期主题'
        assert loaded['body'] == '长期正文'
        assert loaded['attachment_filename'] == '本客户缴费清单.txt'
        assert _attachment_filename(loaded, '模板测试客户', '2026-09') == '本客户缴费清单.txt'

        _save_template(conn, cid, '长期主题', '', '')
        fallback = _attachment_filename(_get_template(conn, cid), '模板测试客户', '2026-09')
        assert fallback == '模板测试客户_2026-09_缴费.txt'

        try:
            _save_template(conn, cid, '主题', '', '非法/名称')
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError('非法附件文件名必须被拒绝')

    print('v0.3 payment template contract passed')


if __name__ == '__main__':
    main()
