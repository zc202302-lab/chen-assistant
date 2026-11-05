"""Two schedule modes and the durable per-business completion gate."""
import json
from datetime import date
from payment_next_date_contract import app, db, init_db, now_iso, create_session, TestClient
from app.payment_schedule import computed_next_date, date_preparation, prepared_service_ids
from app.payment_v02 import current_period
from app.v0212_routes import _payment_snapshot_base_v0212
from app.v031_payment_workflow_routes import _run_v031


def main():
    init_db()
    period = current_period()
    today = date.today().isoformat()
    old_date = period + '-01'
    later = computed_next_date(old_date, 2)
    now = now_iso()
    with db() as conn:
        cid = conn.execute('INSERT INTO customers(name,payment_enabled,created_at,updated_at) VALUES(?,1,?,?)', ('缴费模式测试', now, now)).lastrowid
        ids = []
        for index in range(3):
            ids.append(conn.execute('''INSERT INTO services(customer_id,service_type,number,payment_cycle,payment_interval_months,last_payment_date,next_payment_date,payment_schedule_mode,monthly_fee,fixed_fee)
                VALUES(?,?,?,?,?,?,?,?,?,?)''', (cid, '成员', str(index), '1个月', 1, '2020-01-01', old_date, 'specified', 10, 1)).lastrowid)
        periodic_id = conn.execute('''INSERT INTO services(customer_id,service_type,number,payment_cycle,
            payment_interval_months,last_payment_date,next_payment_date,payment_schedule_mode,monthly_fee,fixed_fee)
            VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (cid, '成员', '周期业务', '1个月', 1, '2020-01-01', '2020-02-01', 'periodic', 10, 1)).lastrowid
        run, _ = _run_v031(conn, cid)
        conn.execute('UPDATE customer_payment_runs SET reviewed_at=?,notified_at=?,initiated_at=? WHERE id=?', (now, now, now, run['id']))
    token, csrf, _ = create_session()
    with TestClient(app) as client:
        client.cookies.set('session_token', token)
        def action(value, expected=200):
            result = client.post(f'/customers/{cid}/payment-workflow-v031', data={'csrf':csrf,'action':value})
            assert result.status_code == expected, result.text
            return result.json()
        def attributes(sid, mode, **values):
            data = client.get(f'/services/{sid}/attributes-v028').json()
            data['values'].update(values)
            result = client.post(f'/services/{sid}/attributes-v028', data={'csrf':csrf,'schedule_mode':mode,'template_json':json.dumps(data['template']),'values_json':json.dumps(data['values'])})
            assert result.status_code == 200, result.text
        action('paid', 409)  # Direct completion cannot bypass date preparation.
        assert len(action('prepare_dates')['date_setup']['remaining']) == 3
        with db() as conn:
            assert periodic_id in prepared_service_ids(conn, cid, period)
        attributes(periodic_id, 'specified', next_payment_date=later)
        with db() as conn:
            items, stats = _payment_snapshot_base_v0212(conn, cid, period)
            assert periodic_id not in prepared_service_ids(conn, cid, period)
            assert {item['row']['id'] for item in items} == set(ids)
            assert stats['total'] == 30
        attributes(ids[0], 'specified', next_payment_date=old_date.replace('-', '/'))
        assert len(action('prepare_dates')['date_setup']['remaining']) == 3  # Same day, different spelling.
        attributes(ids[0], 'specified', next_payment_date=later)
        with db() as conn:
            items, _ = _payment_snapshot_base_v0212(conn, cid, period)
            assert {item['row']['id'] for item in items} == set(ids)  # Moving date must not hide unpaid business.
        action('paid', 409)
        attributes(ids[1], 'periodic')  # Conversion exempts this record without changing its date manually.
        result = client.post(f'/services/{ids[2]}/status-v03', data={'csrf':csrf,'status':'inactive'})
        assert result.status_code == 200, result.text
        assert action('prepare_dates')['date_setup']['remaining'] == []
        result = action('paid')
        assert result['run']['paid']
        with db() as conn:
            rows = {r['id']: r for r in conn.execute('SELECT * FROM services WHERE customer_id=?',(cid,))}
            assert rows[ids[0]]['next_payment_date'] == later
            assert rows[ids[0]]['last_payment_date'] == today
            assert rows[ids[1]]['next_payment_date'] == computed_next_date(today,1)
            assert rows[ids[2]]['last_payment_date'] == '2020-01-01'  # Closed record not renewed.
            assert prepared_service_ids(conn,cid,period) == set()
        assert not action('paid')['run']['paid']
        with db() as conn:
            assert conn.execute('SELECT next_payment_date FROM services WHERE id=?',(ids[0],)).fetchone()[0] == old_date
        # All remaining specified businesses closed: zero date edits required.
        for sid in ids:
            result = client.post(f'/services/{sid}/status-v03',data={'csrf':csrf,'status':'inactive'})
            assert result.status_code == 200
        assert action('prepare_dates')['date_setup']['remaining'] == []
        assert action('paid')['run']['paid']
        # Interactive creation defaults do not rewrite imported/historical records.
        result = client.post(f'/customers/{cid}/services-v026',data={'csrf':csrf,'service_type':'新增默认值'},follow_redirects=False)
        assert result.status_code in (302,303), result.text
        with db() as conn:
            created = conn.execute('SELECT * FROM services WHERE customer_id=? ORDER BY id DESC',(cid,)).fetchone()
            assert created['last_payment_date'] == today
            assert created['payment_interval_months'] == 1
            assert created['payment_schedule_mode'] == 'periodic'
            assert created['next_payment_date'] == computed_next_date(today,1)
    print('payment modes contract passed: date change / mode conversion / closure / rollback / defaults')


if __name__ == '__main__':
    main()
