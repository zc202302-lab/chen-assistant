"""Date overrides, free-text persistence, payment renewal and exact rollback."""
import json
import os
from pathlib import Path
import sys
import tempfile
from datetime import date
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
temporary = tempfile.TemporaryDirectory(prefix='payment-next-date-')
os.environ['APP_DB_PATH'] = str(Path(temporary.name) / 'app.db')
os.environ.update(APP_USERNAME='test', APP_PASSWORD_SALT='dGVzdHNhbHQ=', APP_PASSWORD_HASH='x', APP_SESSION_SECRET='next-date-test', APP_SECURE_COOKIE='0')
os.environ['APP_ENCRYPTION_KEY'] = Fernet.generate_key().decode()

from fastapi.testclient import TestClient
from app.main import app
from app.db import db, init_db, now_iso
from app.security import create_session
from app.payment_schedule import computed_next_date, ensure_payment_date_schema
from app.payment_v02 import service_is_due, current_period
from app.v0212_routes import _natural_due, _service_due
from app.v0212_routes import _payment_snapshot_base_v0212
from app.v028_routes import _template


def main():
    assert computed_next_date('2025-07-12', 12) == '2026-07-12'
    assert computed_next_date('2024-02-29', 12) == '2025-02-28'
    assert computed_next_date('2026/1/31', 1) == '2026-02-28'
    assert computed_next_date('暂不确定', 12) == ''
    assert _natural_due({'payment_interval_months': 12, 'payment_cycle': '12个月', 'last_payment_date': '2026-99-99', 'next_payment_period': '', 'next_payment_date': ''}, '2026-10')
    init_db()
    now = now_iso()
    with db() as conn:
        cid = conn.execute('INSERT INTO customers(name,payment_enabled,created_at,updated_at) VALUES(?,1,?,?)', ('日期测试', now, now)).lastrowid
        sid = conn.execute('''INSERT INTO services(customer_id,service_type,payment_cycle,payment_interval_months,last_payment_date,next_payment_period,monthly_fee,fixed_fee)
            VALUES(?,?,?,?,?,?,?,?)''', (cid, '测试业务', '12个月', 12, '2025-07-12', '2035-01', 20, 1)).lastrowid
        ensure_payment_date_schema(conn)
        template = _template(conn)
        row = conn.execute('SELECT * FROM services WHERE id=?', (sid,)).fetchone()
        assert row['next_payment_date'] == '2026-07-12'
        assert not _natural_due(row, '2026-06')
        assert _natural_due(row, '2026-07')
        assert service_is_due(row, date(2026, 7, 1))
        conn.execute('UPDATE services SET next_payment_date=? WHERE id=?', ('2030-10-12', sid))
        ensure_payment_date_schema(conn)
        row = conn.execute('SELECT * FROM services WHERE id=?', (sid,)).fetchone()
        assert row['next_payment_date'] == '2030-10-12'
        assert not _natural_due(row, '2029-12')
        assert not _service_due(row, {'status': 'inactive'}, '2031-01')
    token, csrf, _ = create_session()
    with TestClient(app) as client:
        client.cookies.set('session_token', token)
        def save(values):
            result = client.post(f'/services/{sid}/attributes-v028', data={'csrf': csrf, 'template_json': json.dumps(template), 'values_json': json.dumps(values)})
            assert result.status_code == 200 and result.headers.get('content-type', '').startswith('application/json'), result.text
        save({'last_payment_date': '2025年7月12日', 'next_payment_date': '另行通知'})
        with db() as conn:
            row = conn.execute('SELECT * FROM services WHERE id=?', (sid,)).fetchone()
            assert row['last_payment_date'] == '2025年7月12日', dict(row)
            assert row['next_payment_date'] == '另行通知'
            assert _natural_due(row, current_period())
        save({'last_payment_date': '2025-07-12'})
        with db() as conn:
            assert conn.execute('SELECT next_payment_date FROM services WHERE id=?', (sid,)).fetchone()[0] == '另行通知'
        # The override makes this annual business due now despite its old 2035 month.
        for action in ('review', 'notify', 'paid'):
            result = client.post(f'/customers/{cid}/payment-run', data={'csrf': csrf, 'action': action})
            assert result.status_code == 200, (action, result.text)
        with db() as conn:
            row = conn.execute('SELECT * FROM services WHERE id=?', (sid,)).fetchone()
            assert row['last_payment_date'] == date.today().isoformat()
            assert row['next_payment_date'] == computed_next_date(date.today().isoformat(), 12)
            assert not _natural_due(row, current_period())
            paid_items, _ = _payment_snapshot_base_v0212(conn, cid, current_period())
            assert [item['row']['id'] for item in paid_items] == [sid]
        result = client.post(f'/customers/{cid}/payment-run', data={'csrf': csrf, 'action': 'paid'})
        assert result.status_code == 200, result.text
        with db() as conn:
            row = conn.execute('SELECT * FROM services WHERE id=?', (sid,)).fetchone()
            assert row['last_payment_date'] == '2025-07-12'
            assert row['next_payment_date'] == '另行通知'
    print('payment next date contract passed: override, calendar, free text, migration, complete and rollback')


if __name__ == '__main__':
    main()
