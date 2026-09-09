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

    actions = (ROOT / 'app' / 'static' / 'v031_workflow_actions.js').read_text(encoding='utf-8')
    for token in (
        'prepareNotice', 'prepareInitiate', 'navigator.clipboard.write', 'ClipboardItem',
        'payment-mail-compose-v031', '127.0.0.1:18763', 'attachment_filename_b64',
        "bridgeFetch('/compose'", '12000', 'Windows Foxmail助手响应超时',
        'verified !== true',
    ):
        assert token in actions, token
    prepare_initiate = actions.split('const prepareInitiate = async () => {', 1)[1].split('\n  };', 1)[0]
    assert "bridgeFetch('/health'" not in prepare_initiate, '发起缴费不得被短时health探测阻断'
    assert "bridgeFetch('/compose'" in prepare_initiate, '发起缴费必须直接以compose确认Foxmail打开'

    runtime_owner = (ROOT / 'app' / 'static' / 'v031_workflow_runtime_fix.js').read_text(encoding='utf-8')
    for token in (
        "['notify', '通知客户'", '待确认 ·', 'notifyPrepared', 'initiatePrepared',
        'prepareNotify', 'prepareInitiate', 'event.stopImmediatePropagation()',
        '确认缴费图片已经通过微信发送给客户', '确认缴费邮件已经在Foxmail中发送给同事',
        "root.querySelectorAll('[data-v031-payment-image],[data-v03-foxmail-draft]')",
        '固定缴费金额自动确认', 'v031-auto-confirmed',
        'window.ChenPaymentWorkflowRuntimeV031', "refresh: () => loadState({quiet: true})",
    ):
        assert token in runtime_owner, token

    rollback = (ROOT / 'app' / 'static' / 'v031_amount_rollback_fix.js').read_text(encoding='utf-8')
    for token in (
        'payment-workflow-v031', 'syncAfterSavedAmount',
        "workbench.addEventListener('focusin'", "workbench.addEventListener('keyup'",
        "e.key !== 'Enter'", 'v031OriginalAmount', 'attempt < 6',
        '原客户通知已失效', '重新发起缴费',
        'ChenPaymentWorkflowRuntimeV031', 'refreshWorkflowOwner',
    ):
        assert token in rollback, token
    assert "fd.append('action', 'invalidate')" not in rollback
    assert 'MutationObserver' not in rollback
    assert 'btn.textContent' not in rollback, '金额回退辅助脚本不得直接改四步按钮'

    fixed_patch = (ROOT / 'app' / 'v031_fixed_review_patch.py').read_text(encoding='utf-8')
    for token in (
        "item['rule']['mode'] == 'fixed'", "item['rule']['mode'] != 'variable'",
        "confirmed=1", "source='fixed_review_reset'", 'fixed_auto_confirmed',
        'workflow._paint_review_reset = _fixed_amount_review',
    ):
        assert token in fixed_patch, token

    guard = (ROOT / 'app' / 'static' / 'v031_workflow_dom_guard.js').read_text(encoding='utf-8')
    for token in (
        'data-v031-flow-action="paid"', 'input.readOnly !== paid',
        '固定缴费金额自动确认', 'v031-fixed-auto-confirmed',
        "attributeFilter: ['readonly', 'disabled', 'data-confirmed']",
    ):
        assert token in guard, token

    routes = (ROOT / 'app' / 'v031_payment_workflow_routes.py').read_text(encoding='utf-8')
    for token in (
        'initiated_at', "action == 'initiate'", "action == 'invalidate'",
        "@router.post('/services/{service_id}/payment-current')",
        'amount_changed', 'workflow_invalidated', '_invalidate_after_amount_change',
        '请先完成“发起缴费”', 'payment-mail-compose-v031', "'version': '0.3.1'",
    ):
        assert token in routes, token

    from app.main import app  # noqa: E402
    matches = [
        r for r in app.router.routes
        if getattr(r, 'path', '') == '/services/{service_id}/payment-current'
        and 'POST' in getattr(r, 'methods', set())
    ]
    assert matches
    assert matches[0].endpoint.__module__ == 'app.v031_payment_workflow_routes'

    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert 'v0.3.1' in base
    assert '/static/v031_workflow_actions.js?v=0315' in base
    assert '/static/v031_workflow_runtime_fix.js?v=0314' in base
    assert '/static/v031_workflow_dom_guard.js?v=0314' in base
    assert '/static/v031_payment_workflow.css?v=0314' in base
    assert base.index('/static/v031_workflow_actions.js') > base.index('/static/v031_payment_workflow.js')
    assert base.index('/static/v031_workflow_runtime_fix.js') > base.index('/static/v031_workflow_actions.js')
    assert base.index('/static/v031_workflow_dom_guard.js') > base.index('/static/v031_workflow_runtime_fix.js')

    css = (ROOT / 'app' / 'static' / 'v031_payment_workflow.css').read_text(encoding='utf-8')
    for token in ('.awaiting-confirm', '.current', '.done', '.v031-fixed-auto-confirmed'):
        assert token in css, token

    print('v0.3.1 integrated workflow contract passed')


if __name__ == '__main__':
    main()
