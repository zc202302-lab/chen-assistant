from __future__ import annotations

import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / 'data' / 'app.db'
for suffix in ('', '-wal', '-shm'):
    p = Path(str(DB) + suffix)
    if p.exists():
        p.unlink()

os.environ.update({
    'APP_USERNAME': 'ui-test',
    'APP_PASSWORD_SALT': 'dGVzdHNhbHQ=',
    'APP_PASSWORD_HASH': 'x',
    'APP_SESSION_SECRET': 'ui-test-session-secret',
    'APP_ENCRYPTION_KEY': 'x',
    'APP_SECURE_COOKIE': '0',
})

from fastapi.testclient import TestClient  # noqa: E402
from app.db import db, init_db, now_iso  # noqa: E402
from app.main import app  # noqa: E402
from app.payment_v02 import current_period  # noqa: E402
from app.security import create_session  # noqa: E402


def seed():
    init_db()
    now = now_iso()
    period = current_period()
    with db() as conn:
        cid = int(conn.execute(
            'INSERT INTO customers (name,group_code,tax_id,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            ('布局修订客户', 'LAYOUT', 'LAYOUT-TAX', 1, now, now),
        ).lastrowid)
        sid = int(conn.execute(
            '''INSERT INTO services
               (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                payment_cycle,payment_interval_months,active_from_period,sort_order,source_row,
                payment_method,invoice_type,package_type,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (cid, '成员', '后勤', '13800138029', '5338000038029', 88, 0,
             '1个月', 1, period, 10, 1, '微信', '普票', '重点套餐', '备注'),
        ).lastrowid)
        conn.execute(
            'INSERT INTO service_payment_rules (service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)',
            (sid, '1900-01', 'variable', 0, now),
        )
        for name, expiry in (
            ('已到期优惠', date.today()),
            ('即将到期优惠', date.today() + timedelta(days=30)),
        ):
            conn.execute(
                '''INSERT INTO promotions(service_id,name,start_date,expiry_date,remind_days,status,notes,created_at)
                   VALUES(?,?,?,?,?,?,?,?)''',
                (sid, name, '', expiry.isoformat(), 60, 'active', '', now),
            )
    token, _, _ = create_session()
    return cid, token


def main():
    cid, token = seed()
    client = TestClient(app)
    client.cookies.set('session_token', token)

    business = client.get(f'/customers/{cid}?tab=services')
    assert business.status_code == 200, business.text
    match = re.search(r'<article class="business-row-v028".*?</article>', business.text, re.S)
    assert match, 'business row missing'
    row = match.group(0)
    assert 'business-derived' not in row, 'derived payment/promotion badges still occupy business row'
    assert row.count('class="business-attribute"') == 5, 'business preview must show exactly first five attributes'
    assert 'business-edit-v029' in row, 'edit action missing from the same business row'

    home = client.get('/?home=promos')
    assert home.status_code == 200, home.text
    expired = re.search(r'<section class="home-promo-column-v030 state-expired">.*?</section>', home.text, re.S)
    soon = re.search(r'<section class="home-promo-column-v030 state-soon">.*?</section>', home.text, re.S)
    assert expired and soon, 'home promotion page is not split into expired/soon columns'
    assert '布局修订客户' in expired.group(0), 'expired column missing customer'
    assert '布局修订客户' in soon.group(0), 'soon column missing customer'

    css = (ROOT / 'app' / 'static' / 'layout-refinement.css').read_text(encoding='utf-8')
    assert 'grid-template-columns:minmax(0,1fr) minmax(0,1fr)' in css
    assert '.business-attribute:nth-child(n+6){display:none}' in css
    print('layout refinement regression passed')


if __name__ == '__main__':
    main()
