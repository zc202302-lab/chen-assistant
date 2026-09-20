from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v031-workflow-')
os.environ['APP_DB_PATH'] = str(Path(_TMPDIR.name) / 'app.db')

from app import config  # noqa: E402
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
        "bridgeFetch('/compose'", '22000', 'Windows Foxmail助手响应超时',
        'verified !== true', 'stable, foreground Foxmail compose window',
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
        '金额刚刚修改，请重新确认这一条', 'row?.dataset.confirmed',
        'window.ChenPaymentWorkflowRuntimeV031', "refresh: () => loadState({quiet: true})",
        "event.target.closest?.('[data-review-toggle]')",
    ):
        assert token in runtime_owner, token

    # v0.3.3 keeps the runtime's two-step external-action state model, but the
    # late-loaded patch removes all payment-stage alert/confirm dialogs and owns
    # deterministic browser TXT/EXCEL downloading.
    nonblocking = (ROOT / 'app' / 'static' / 'v033_payment_flow_patch.js').read_text(encoding='utf-8')
    for token in (
        'window.confirm = message =>', 'window.alert = message =>',
        '确认缴费图片已经通过微信发送给客户',
        '确认缴费邮件已经在Foxmail中发送给同事',
        '确认同事已收到邮件，并且你已经完成本次实际支付',
        '撤回“完成缴费”并恢复本次缴费前的周期状态',
        '该客户已经发起缴费。修改金额后',
        'URL.createObjectURL(blob)', 'download.download =', 'toast(`缴费${label}已下载`)',
        "id: 'paymentExcelButton', label: 'EXCEL'", "id: 'paymentTxtButton', label: 'TXT'",
    ):
        assert token in nonblocking, token

    rollback = (ROOT / 'app' / 'static' / 'v031_amount_rollback_fix.js').read_text(encoding='utf-8')
    for token in (
        'payment-workflow-v031', 'syncAfterSavedAmount',
        "workbench.addEventListener('focusin'", "workbench.addEventListener('keyup'",
        "e.key !== 'Enter'", 'v031OriginalAmount', 'attempt < 6',
        'ChenPaymentWorkflowRuntimeV031', 'refreshWorkflowOwner',
    ):
        assert token in rollback, token
    assert "fd.append('action', 'invalidate')" not in rollback
    assert 'MutationObserver' not in rollback
    assert 'btn.textContent' not in rollback, '金额回退辅助脚本不得直接改四步按钮'

    patch = (ROOT / 'app' / 'v031_fixed_review_patch.py').read_text(encoding='utf-8')
    for token in (
        'MANUAL_CHANGED_SOURCE', "confirmed = 0", "source = MANUAL_CHANGED_SOURCE",
        '_review_snapshot', '_auto_review_run', '_rollback_completed_payment',
        'payment_save_preserve_reviews_v032', 'payment_review_toggle_preserve_reviews_v032',
        'core.payment_snapshot_v0212 = _review_snapshot',
        'workflow._run_v031 = _auto_review_run',
        'workflow._paint_review_reset = _fixed_amount_review',
        "reviewed_at='',notified_at='',initiated_at='',paid_at=''",
    ):
        assert token in patch, token

    guard = (ROOT / 'app' / 'static' / 'v031_workflow_dom_guard.js').read_text(encoding='utf-8')
    for token in (
        'data-v031-flow-action="paid"', "document.addEventListener('beforeinput'",
        'event.stopPropagation()', 'if (input.readOnly) input.readOnly = false',
        '金额刚刚修改，请重新确认这一条', 'v031-fixed-auto-confirmed',
        "attributeFilter: ['readonly', 'disabled', 'data-confirmed', 'data-mode']",
    ):
        assert token in guard, token

    routes = (ROOT / 'app' / 'v031_payment_workflow_routes.py').read_text(encoding='utf-8')
    for token in (
        'initiated_at', "action == 'initiate'", "action == 'invalidate'",
        '_invalidate_after_amount_change', '请先完成“发起缴费”',
        'payment-mail-compose-v031', "'version': config.APP_VERSION",
    ):
        assert token in routes, token

    from app.main import app  # noqa: E402
    assert app.version == config.APP_VERSION
    for path, endpoint in (
        ('/services/{service_id}/payment-current', 'payment_save_preserve_reviews_v032'),
        ('/services/{service_id}/payment-review-toggle', 'payment_review_toggle_preserve_reviews_v032'),
    ):
        matches = [
            r for r in app.router.routes
            if getattr(r, 'path', '') == path and 'POST' in getattr(r, 'methods', set())
        ]
        assert matches, path
        assert matches[0].endpoint.__module__ == 'app.v031_fixed_review_patch'
        assert matches[0].endpoint.__name__ == endpoint

    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert 'v{{ request.app.version }}' in base
    assert '/static/v031_workflow_actions.js?v=0316' in base
    assert '/static/v031_workflow_runtime_fix.js?v=0314' in base
    assert '/static/v031_workflow_dom_guard.js?v=0315' in base
    assert '/static/v033_payment_flow_patch.js?v=1560' in base
    assert '/static/v031_payment_workflow.css?v=0314' in base
    assert base.index('/static/v031_workflow_actions.js') > base.index('/static/v031_payment_workflow.js')
    assert base.index('/static/v031_workflow_runtime_fix.js') > base.index('/static/v031_workflow_actions.js')
    assert base.index('/static/v031_workflow_dom_guard.js') > base.index('/static/v031_workflow_runtime_fix.js')
    assert base.index('/static/v033_payment_flow_patch.js') > base.index('/static/v031_workflow_dom_guard.js')

    css = (ROOT / 'app' / 'static' / 'v031_payment_workflow.css').read_text(encoding='utf-8')
    for token in ('.awaiting-confirm', '.current', '.done', '.v031-fixed-auto-confirmed'):
        assert token in css, token

    print('v0.3.3 automatic review + fully nonblocking workflow + real TXT download contract passed')


if __name__ == '__main__':
    main()
