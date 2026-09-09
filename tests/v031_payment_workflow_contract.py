from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v031-workflow-')
os.environ['APP_DB_PATH'] = str(Path(_TMPDIR.name) / 'app.db')

from app.db import db, init_db, now_iso  # noqa: E402
from app.v031_payment_workflow_routes import ensure_v031  # noqa: E402


def main():
    init_db()
    now = now_iso()
    with db() as conn:
        cid = int(conn.execute(
            'INSERT INTO customers(name,created_at,updated_at) VALUES(?,?,?)',
            ('v031测试客户', now, now),
        ).lastrowid)
        rid = int(conn.execute(
            '''INSERT INTO customer_payment_runs(customer_id,period,notified_at,paid_at,created_at,updated_at)
               VALUES(?,?,?,?,?,?)''',
            (cid, '2026-09', now, now, now, now),
        ).lastrowid)
        ensure_v031(conn)
        cols = {row['name'] for row in conn.execute('PRAGMA table_info(customer_payment_runs)')}
        assert 'initiated_at' in cols
        row = conn.execute('SELECT initiated_at,paid_at FROM customer_payment_runs WHERE id=?', (rid,)).fetchone()
        assert row['initiated_at'] == row['paid_at'] == now

    js = (ROOT / 'app' / 'static' / 'v031_payment_workflow.js').read_text(encoding='utf-8')
    for token in (
        '生成缴费图片', '已通知客户', '发起缴费', '完成缴费',
        'navigator.clipboard.write', 'ClipboardItem',
        'payment-mail-compose-v031', 'payment-workflow-v031',
        "['review', '金额核对']", "['notify', '已通知客户']",
        "['initiate', '发起缴费']", "['paid', '完成缴费']",
        "postAction('invalidate')",
    ):
        assert token in js, token

    routes = (ROOT / 'app' / 'v031_payment_workflow_routes.py').read_text(encoding='utf-8')
    for token in (
        "initiated_at", "action == 'initiate'", "action == 'invalidate'",
        '请先完成“发起缴费”', 'payment-mail-compose-v031',
        "'version': '0.3.1'",
    ):
        assert token in routes, token

    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert 'v0.3.1' in base
    assert '/static/v031_payment_workflow.js?v=0310' in base
    assert '/static/v031_payment_workflow.css?v=0310' in base

    print('v0.3.1 payment workflow contract passed')


if __name__ == '__main__':
    main()
