"""Customer display settings survive server rendering and live-refresh HTML."""
import json
import re

from payment_next_date_contract import (
    ROOT, app, db, init_db, now_iso, create_session, _template,
)
from fastapi.testclient import TestClient
from app.v027_routes import _meta_set
from app.v028_routes import TEMPLATE_META_KEY
from app.v0212_business_display_routes import BUSINESS_DISPLAY_ORDER_KEY


LEGACY = ['holder_name', 'number', 'account']
CUSTOM_KEY = 'custom_123456789abc'
SELECTED = [*LEGACY, CUSTOM_KEY, 'notes', 'last_payment_date']


def seed():
    init_db()
    with db() as conn:
        now = now_iso()
        template = _template(conn)
        _meta_set(conn, TEMPLATE_META_KEY, json.dumps([
            *template, {'key': CUSTOM_KEY, 'label': '测试金额', 'kind': 'integer', 'core': False},
        ]))
        _meta_set(conn, BUSINESS_DISPLAY_ORDER_KEY, json.dumps(LEGACY))
        result = []
        for index in range(2):
            cid = conn.execute(
                'INSERT INTO customers(name,payment_enabled,created_at,updated_at) VALUES(?,1,?,?)',
                (f'显示属性测试{index}', now, now),
            ).lastrowid
            sid = conn.execute('''INSERT INTO services(customer_id,service_type,holder_name,number,account,
                payment_interval_months,payment_cycle,last_payment_date,notes,monthly_fee,fixed_fee)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                (cid, '成员', f'测试成员{index}', f'1580000000{index}', f'5338000000{index}',
                 1, '1个月', '2026-09-12', '备注测试', 20, 1)).lastrowid
            conn.execute('INSERT INTO service_custom_attributes(service_id,attr_key,value) VALUES(?,?,?)',
                         (sid, CUSTOM_KEY, '35'))
            result.append((cid, sid))
        return result


def rendered_keys(html, sid):
    rows = re.findall(r'<article\b[^>]*data-business-row[^>]*>.*?</article>', html, re.S)
    row = next(row for row in rows if f'data-service-id="{sid}"' in row)
    return re.findall(r'data-attr-key="([^"]+)"', row)


def main():
    (cid, sid), (other_cid, other_sid) = seed()
    token, csrf, _ = create_session()
    with TestClient(app) as client:
        client.cookies.set('session_token', token)
        url = f'/customers/{cid}/business-columns-v0212'
        for keys in [SELECTED, ['next_payment_date', 'number'], []]:
            result = client.post(url, data={'csrf': csrf, 'columns_json': json.dumps(keys)})
            assert result.status_code == 200, result.text
            assert result.json()['columns'] == keys
            assert [a['key'] for a in result.json()['rows'][str(sid)]['preview_attributes']] == keys
            assert client.get(url).json()['columns'] == keys
            # Both a full reload and the automatic refresh must read the same
            # customer configuration, not the old global three-column default.
            for headers in [{}, {'X-Chen-Live-Refresh': '1'}]:
                page = client.get(f'/customers/{cid}?tab=services', headers=headers)
                assert page.status_code == 200, page.text
                assert rendered_keys(page.text, sid) == keys, (keys, rendered_keys(page.text, sid))
            runtime = client.get(f'/services/{sid}/runtime-v0212')
            assert runtime.json()['business_visible_keys'] == keys
            other = client.get(f'/customers/{other_cid}?tab=services')
            assert rendered_keys(other.text, other_sid) == LEGACY
        rejected = client.post(url, data={'csrf': 'invalid', 'columns_json': json.dumps(SELECTED)})
        assert rejected.status_code == 403
        assert client.get(url).json()['columns'] == []
    print('business display settings contract passed: save, render, live refresh, empty and customer isolation')


if __name__ == '__main__':
    main()
