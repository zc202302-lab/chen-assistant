from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v159-payment-safety-')
os.environ['APP_DB_PATH'] = str(Path(_TMPDIR.name) / 'app.db')

from fastapi import HTTPException  # noqa: E402
from app.db import db, init_db, now_iso  # noqa: E402
from app import v0212_routes as core  # noqa: E402
from app.v031_payment_workflow_routes import (  # noqa: E402
    _run_v031,
    _set_initiate_prepared,
    ensure_v031,
)
from app.v033_payment_flow_patch import (  # noqa: E402
    _current_payment_txt_content,
    _ensure_customer_payment_template,
    _get_customer_template,
    _require_excel_attachment_filename,
    _save_customer_template,
)


def fake_item(service_id: int, number: str, amount: float, *, confirmed: bool = True, mode: str = 'variable'):
    return {
        'row': {'id': service_id, 'number': number},
        'payment': {'amount': amount, 'confirmed': 1 if confirmed else 0},
        'rule': {'mode': mode},
        'delta': None,
    }


def main():
    init_db()
    now = now_iso()
    with db() as conn:
        cid = int(conn.execute(
            'INSERT INTO customers(name,created_at,updated_at) VALUES(?,?,?)',
            ('v159缴费安全测试客户', now, now),
        ).lastrowid)
        conn.execute(
            '''INSERT INTO customer_payment_runs(customer_id,period,notified_at,paid_at,created_at,updated_at)
               VALUES(?,?,?,?,?,?)''',
            (cid, '2026-09', now, '', now, now),
        )
        ensure_v031(conn)

        # Persisted "prepared, awaiting manual confirmation" state must survive a DB
        # reread; it is not allowed to exist only in a browser variable.
        run, _ = _run_v031(conn, cid, '2026-09')
        assert run['notified'] is True
        assert run['initiate_prepared'] is False
        _set_initiate_prepared(conn, cid, '2026-09', run)

    with db() as conn:
        reread, _ = _run_v031(conn, cid, '2026-09')
        assert reread['initiate_prepared'] is True
        assert reread['initiate_prepared_at']
        assert reread['initiated'] is False

        _ensure_customer_payment_template(conn)
        saved = _save_customer_template(
            conn, cid, 'pay@example.com', '缴费主题', '正文',
            '正式缴费TXT', '正式缴费EXCEL',
        )
        assert saved['attachment_filename'] == '正式缴费TXT.txt'
        assert saved['excel_attachment_filename'] == '正式缴费EXCEL.xlsx'
        assert _require_excel_attachment_filename(_get_customer_template(conn, cid)) == '正式缴费EXCEL.xlsx'

    original_snapshot = core.payment_snapshot_v0212
    try:
        expected_items = [
            fake_item(1, '5330022649502', 225),
            fake_item(2, '5330022457921', 225),
            fake_item(3, '5330023910210', 1),
            fake_item(4, '15753325327', 55),
            fake_item(5, '15753325502', 105),
            fake_item(6, '15006537997', 115),
            fake_item(7, '15153317997', 135),
        ]

        def reviewed_snapshot(conn, customer_id, period):
            return expected_items, {
                'due_count': len(expected_items),
                'required': len(expected_items),
                'pending': 0,
                'changed': 0,
                'zero': 0,
                'total': 861,
                'txt_ready': True,
            }

        core.payment_snapshot_v0212 = reviewed_snapshot
        with db() as conn:
            _, body, stats = _current_payment_txt_content(conn, cid, '2026-09')
        assert stats['pending'] == 0
        expected = '\r\n'.join([
            '5330022649502|225',
            '5330022457921|225',
            '5330023910210|1',
            '15753325327|55',
            '15753325502|105',
            '15006537997|115',
            '15153317997|135',
        ])
        assert body == expected
        assert hashlib.sha256(body.encode('utf-8')).hexdigest()
        pairs = [line.split('|') for line in body.split('\r\n')]
        assert pairs == [
            [(item['row']['number']), str(int(item['payment']['amount']))]
            for item in expected_items
        ]

        # A positive fixed row manually made pending must also block formal TXT.
        fixed_pending = [fake_item(10, '13800138000', 88, confirmed=False, mode='fixed')]

        def fixed_pending_snapshot(conn, customer_id, period):
            return fixed_pending, {
                'due_count': 1, 'required': 1, 'pending': 0,
                'changed': 0, 'zero': 0, 'total': 88, 'txt_ready': True,
            }

        core.payment_snapshot_v0212 = fixed_pending_snapshot
        with db() as conn:
            try:
                _current_payment_txt_content(conn, cid, '2026-09')
            except HTTPException as exc:
                assert exc.status_code == 409
                assert '未核对' in str(exc.detail)
            else:
                raise AssertionError('未核对的固定缴费行不得进入正式TXT')

        # A payable row may never be silently emitted without its number.
        missing_number = [fake_item(11, '', 66)]

        def missing_number_snapshot(conn, customer_id, period):
            return missing_number, {
                'due_count': 1, 'required': 1, 'pending': 0,
                'changed': 0, 'zero': 0, 'total': 66, 'txt_ready': True,
            }

        core.payment_snapshot_v0212 = missing_number_snapshot
        with db() as conn:
            try:
                _current_payment_txt_content(conn, cid, '2026-09')
            except HTTPException as exc:
                assert exc.status_code == 409
                assert '未填写号码' in str(exc.detail)
            else:
                raise AssertionError('非0金额缺少号码时必须停止TXT生成')

        bad_number = [fake_item(12, '138|00138000', 77)]

        def bad_number_snapshot(conn, customer_id, period):
            return bad_number, {
                'due_count': 1, 'required': 1, 'pending': 0,
                'changed': 0, 'zero': 0, 'total': 77, 'txt_ready': True,
            }

        core.payment_snapshot_v0212 = bad_number_snapshot
        with db() as conn:
            try:
                _current_payment_txt_content(conn, cid, '2026-09')
            except HTTPException as exc:
                assert exc.status_code == 409
                assert '号码格式异常' in str(exc.detail)
            else:
                raise AssertionError('号码包含TXT分隔符时必须停止生成')
    finally:
        core.payment_snapshot_v0212 = original_snapshot

    helper = (ROOT / 'app/static/chen_foxmail_helper_v09.ps1').read_text(encoding='ascii')
    for token in (
        'Set-AttachmentClipboard',
        '[System.Windows.Forms.Clipboard]::SetFileDropList',
        'attachment_clipboard_verified = $true',
        'attachment_integrity_verified = $true',
        "explorer_dispatched = $false",
        "Join-Path $env:TEMP 'ChenAssistantPaymentClipboard'",
        'Schedule-ClipboardFileCleanup',
        'Get-FileHash -Algorithm SHA256',
    ):
        assert token in helper, token
    assert "Start-Process -FilePath 'explorer.exe'" not in helper

    route = (ROOT / 'app/v033_payment_flow_patch.py').read_text(encoding='utf-8')
    for token in (
        'attachment_sha256',
        'attachment_line_count',
        '缴费TXT号码与金额对应关系校验失败',
        '_require_excel_attachment_filename',
        'excel_attachment_filename',
    ):
        assert token in route, token

    print('v1.5.9 payment initiation/TXT safety contract passed')


if __name__ == '__main__':
    main()
