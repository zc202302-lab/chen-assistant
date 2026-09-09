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

    rollback = (ROOT / 'app' / 'static' / 'v031_amount_rollback_fix.js').read_text(encoding='utf-8')
    for token in (
        'payment-workflow-v031', 'syncAfterSavedAmount',
        "workbench.addEventListener('focusin'", "workbench.addEventListener('keyup'",
        "e.key !== 'Enter'", 'v031OriginalAmount', 'attempt < 6',
        '原客户通知已失效', '重新发起缴费',
    ):
        assert token in rollback, token
    assert "fd.append('action', 'invalidate')" not in rollback, '前端兜底不应再负责写入回退状态'
    assert 'MutationObserver' not in rollback, '金额回退不得监听页面统计变化，避免正常核对被误回退'

    runtime_owner = (ROOT / 'app' / 'static' / 'v031_workflow_runtime_fix.js').read_text(encoding='utf-8')
    for token in (
        'sole runtime controller' if False else 'Capture phase deliberately takes ownership',
        "flow.addEventListener('click'", 'event.stopImmediatePropagation()',
        'payment-workflow-v031', 'data-v031-workflow-ready' if False else 'v031WorkflowReady',
        'setTimeout(() => loadState({quiet: true}), 1000)',
    ):
        assert token in runtime_owner, token

    routes = (ROOT / 'app' / 'v031_payment_workflow_routes.py').read_text(encoding='utf-8')
    for token in (
        "initiated_at", "action == 'initiate'", "action == 'invalidate'",
        "@router.post('/services/{service_id}/payment-current')",
        'amount_changed', 'workflow_invalidated', '_invalidate_after_amount_change',
        '请先完成“发起缴费”', 'payment-mail-compose-v031',
        "'version': '0.3.1'",
    ):
        assert token in routes, token

    # v0.3.1 must own the public amount-save route so save + workflow rollback are atomic.
    from app.main import app  # noqa: E402
    matches = [
        r for r in app.router.routes
        if getattr(r, 'path', '') == '/services/{service_id}/payment-current'
        and 'POST' in getattr(r, 'methods', set())
    ]
    assert matches, '缺少 payment-current POST 路由'
    assert matches[0].endpoint.__module__ == 'app.v031_payment_workflow_routes', matches[0].endpoint.__module__

    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert 'v0.3.1' in base
    assert '/static/v031_payment_workflow.js?v=0311' in base
    assert '/static/v031_amount_rollback_fix.js?v=0311' in base
    assert '/static/v031_workflow_runtime_fix.js?v=0312' in base
    assert '/static/v031_payment_workflow.css?v=0311' in base
    assert base.index('/static/v031_amount_rollback_fix.js') > base.index('/static/v031_payment_workflow.js')
    assert base.index('/static/v031_workflow_runtime_fix.js') > base.index('/static/v031_amount_rollback_fix.js')

    print('v0.3.1 payment workflow contract passed')


if __name__ == '__main__':
    main()
