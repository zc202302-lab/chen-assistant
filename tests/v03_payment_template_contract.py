from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v033-payment-template-contract-')
os.environ['APP_DB_PATH'] = str(Path(_TMPDIR.name) / 'app.db')

from fastapi import HTTPException  # noqa: E402
from app.db import db, init_db, now_iso  # noqa: E402
from app.v033_payment_flow_patch import (  # noqa: E402
    _ensure_customer_payment_template,
    _get_customer_template,
    _require_template,
    _save_customer_template,
)


def main():
    init_db()
    now = now_iso()
    with db() as conn:
        cid1 = int(conn.execute(
            'INSERT INTO customers(name,created_at,updated_at) VALUES(?,?,?)',
            ('模板测试客户A', now, now),
        ).lastrowid)
        cid2 = int(conn.execute(
            'INSERT INTO customers(name,created_at,updated_at) VALUES(?,?,?)',
            ('模板测试客户B', now, now),
        ).lastrowid)

        # Simulate the older table: v0.3.3 must migrate in-place without copying
        # any global recipient or inventing attachment names for a customer.
        conn.execute('DROP TABLE IF EXISTS customer_mail_templates_v03')
        conn.execute(
            '''CREATE TABLE customer_mail_templates_v03 (
                   customer_id INTEGER PRIMARY KEY REFERENCES customers(id) ON DELETE CASCADE,
                   subject TEXT NOT NULL DEFAULT '',
                   body TEXT NOT NULL DEFAULT '',
                   updated_at TEXT NOT NULL DEFAULT ''
               )'''
        )
        _ensure_customer_payment_template(conn)
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(customer_mail_templates_v03)')}
        assert 'recipient' in columns
        assert 'attachment_filename' in columns

        saved = _save_customer_template(
            conn,
            cid1,
            'pay-a@example.com',
            '长期主题A',
            '长期正文A',
            '客户A缴费清单',
        )
        assert saved['recipient'] == 'pay-a@example.com'
        assert saved['attachment_filename'] == '客户A缴费清单.txt'

        loaded1 = _get_customer_template(conn, cid1)
        loaded2 = _get_customer_template(conn, cid2)
        assert loaded1['recipient'] == 'pay-a@example.com'
        assert loaded1['subject'] == '长期主题A'
        assert loaded1['body'] == '长期正文A'
        assert loaded1['attachment_filename'] == '客户A缴费清单.txt'

        # One customer, one template: B must stay completely blank instead of
        # inheriting A/global values or an auto-generated filename.
        assert loaded2 == {
            'recipient': '',
            'subject': '',
            'body': '',
            'attachment_filename': '',
            'updated_at': '',
        }
        try:
            _require_template(loaded2)
        except HTTPException as exc:
            assert exc.status_code == 400
            assert '收件人' in str(exc.detail)
            assert '邮件主题' in str(exc.detail)
            assert 'TXT附件文件名' in str(exc.detail)
        else:
            raise AssertionError('空白客户模板必须只提示缺失字段，不能自动补全')

        # Body remains optional, while the three routing/attachment fields are
        # explicit customer data.
        saved2 = _save_customer_template(
            conn,
            cid2,
            'pay-b@example.com',
            '长期主题B',
            '',
            '客户B.txt',
        )
        _require_template(saved2)
        assert saved2['body'] == ''
        assert _get_customer_template(conn, cid1)['recipient'] == 'pay-a@example.com'

        try:
            _save_customer_template(conn, cid2, 'pay-b@example.com', '主题', '', '非法/名称')
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError('非法附件文件名必须被拒绝')

    print('v0.3.3 customer-scoped payment template contract passed')


if __name__ == '__main__':
    main()
