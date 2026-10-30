"""Customer ordering persistence, filtered slots, stale writes and auth boundaries."""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from business_display_settings_contract import ROOT, seed as base_seed, create_session, db
from app.main import app
from app.customer_order import directory_order
from fastapi.testclient import TestClient


def seed():
    base_seed()
    with db() as conn:
        for name in ['Alpha', 'Bravo', 'Charlie', 'Delta']:
            conn.execute("INSERT INTO customers(name,created_at,updated_at) VALUES(?,?,?)", (name, '2026-10-30', '2026-10-30'))
        return directory_order(conn)[0]


def order():
    with db() as conn:
        return directory_order(conn)


def rendered_ids(html):
    return [int(value) for value in re.findall(r'data-customer-order-id="(\d+)"', html)]


def main():
    ids = seed()
    token, csrf, _ = create_session()
    with TestClient(app) as client:
        client.cookies.set('session_token', token)
        def save(items, revision=None, **extra):
            payload = {'csrf': csrf, 'ids_json': json.dumps(items), 'revision': revision or order()[1]}
            payload.update(extra)
            return client.post('/customers/order', data=payload)
        assert rendered_ids(client.get('/customers').text) == ids
        reverse = ids[::-1]
        initial_revision = order()[1]
        assert save(reverse).status_code == 200
        assert rendered_ids(client.get('/customers').text) == reverse
        assert order()[0] == reverse
        assert save(ids, initial_revision).status_code == 409
        assert order()[0] == reverse
        # Reorder a filtered subset in its original global slots.
        subset = reverse[::2]
        replacement = iter(subset[::-1])
        expected = [next(replacement) if cid in subset else cid for cid in reverse]
        assert save(subset[::-1]).status_code == 200
        assert order()[0] == expected
        assert rendered_ids(client.get('/customers?q=Alpha').text) == [ids[0]]
        for bad in [[], [True], ['1'], [ids[0], ids[0]], [9999999], {'id': ids[0]}]:
            assert save(bad).status_code == 400, bad
            assert order()[0] == expected
        assert save(ids, csrf='bad').status_code == 403
        assert save(ids, ids_json='{').status_code == 400
        # New customers append without displacing saved cards; deleted IDs vanish.
        with db() as conn:
            new = conn.execute("INSERT INTO customers(name,created_at,updated_at) VALUES('A new', '', '')").lastrowid
        assert order()[0] == [*expected, new]
        stale = order()[1]
        with db() as conn:
            conn.execute('DELETE FROM customers WHERE id=?', (new,))
        assert save(expected, stale).status_code == 409
        revision = order()[1]
        def concurrent(items):
            return client.post('/customers/order', data={'csrf': csrf, 'ids_json':json.dumps(items), 'revision': revision}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(concurrent, [expected[::-1], expected[1:] + expected[:1]]))
        assert sorted(codes) == [200, 409], codes
        assert client.get(f'/customers/{ids[0]}').status_code == 200
    with TestClient(app) as anonymous:
        assert anonymous.post('/customers/order', data={'csrf':csrf, 'revision':order()[1], 'ids_json':json.dumps(ids)}, follow_redirects=False).status_code in (302, 303, 401)
    print('customer order contract passed: persistence, filtered slots, new/delete, validation, CSRF, concurrent writes')


if __name__ == '__main__':
    main()
