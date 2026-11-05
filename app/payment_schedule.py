"""Free-text payment dates with explicit, month-based reminder semantics."""
from datetime import date
import calendar
import re
import json


def readable_date(value):
    raw = str(value or '').strip()
    match = re.fullmatch(r'(\d{4})[-/年.](\d{1,2})(?:[-/月.](\d{1,2})日?)?月?', raw)
    if not match:
        return None
    try:
        return date(int(match[1]), int(match[2]), int(match[3] or 1))
    except ValueError:
        return None


def computed_next_date(last, months):
    previous = readable_date(last)
    if previous is None or not months or int(months) <= 0:
        return ''
    index = previous.year * 12 + previous.month - 1 + int(months)
    year, month = index // 12, index % 12 + 1
    if not 1 <= year <= 9999:
        return ''
    return date(year, month, min(previous.day, calendar.monthrange(year, month)[1])).isoformat()


def explicit_payment_date(service):
    if 'next_payment_date' not in service.keys():
        return ''
    if stored_schedule_mode(service) == 'periodic':
        return computed_next_date(service['last_payment_date'], service['payment_interval_months'])
    value = service['next_payment_date']
    if value is None:
        return computed_next_date(service['last_payment_date'], service['payment_interval_months'])
    return str(value).strip()


def explicit_due(service, period):
    """None means no override; unknown text stays visible to avoid missed reminders."""
    raw = explicit_payment_date(service)
    if not raw:
        return False if stored_schedule_mode(service) == 'specified' else None
    parsed = readable_date(raw)
    return True if parsed is None else period >= parsed.strftime('%Y-%m')


def ensure_payment_date_schema(conn=None):
    if conn is None:
        from .db import db
        with db() as owned:
            ensure_payment_date_schema(owned)
        return
    conn.execute('''CREATE TABLE IF NOT EXISTS payment_date_preparations (
        customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
        period TEXT NOT NULL, items_json TEXT NOT NULL, PRIMARY KEY(customer_id,period))''')
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(services)')}
    if 'next_payment_date' not in columns:
        conn.execute('ALTER TABLE services ADD COLUMN next_payment_date TEXT DEFAULT NULL')
    if 'payment_schedule_mode' not in columns:
        conn.execute("ALTER TABLE services ADD COLUMN payment_schedule_mode TEXT NOT NULL DEFAULT 'legacy'")
        for service in conn.execute('SELECT * FROM services').fetchall():
            conn.execute('UPDATE services SET payment_schedule_mode=? WHERE id=?', (inferred_schedule_mode(service),service['id']))
    for row in conn.execute('SELECT id,last_payment_date,payment_interval_months FROM services WHERE next_payment_date IS NULL').fetchall():
        value = computed_next_date(row['last_payment_date'], row['payment_interval_months'])
        conn.execute('UPDATE services SET next_payment_date=? WHERE id=?', (value, row['id']))


MODES = {'periodic', 'specified'}


def stored_schedule_mode(service):
    return service['payment_schedule_mode'] if 'payment_schedule_mode' in service.keys() else 'legacy'


def inferred_schedule_mode(service):
    mode = stored_schedule_mode(service)
    if mode in MODES:
        return mode
    raw = service['next_payment_date'] if 'next_payment_date' in service.keys() else None
    auto = computed_next_date(service['last_payment_date'], service['payment_interval_months'])
    return 'specified' if raw and str(raw).strip() != auto else 'periodic'


def prepared_service_ids(conn, customer_id, period):
    row = conn.execute('SELECT items_json FROM payment_date_preparations WHERE customer_id=? AND period=?',
                       (customer_id, period)).fetchone()
    return {int(item['id']) for item in json.loads(row[0])} if row else set()


def date_preparation(conn, customer_id, period, items, *, create=False):
    row = conn.execute('SELECT items_json FROM payment_date_preparations WHERE customer_id=? AND period=?',
                       (customer_id, period)).fetchone()
    originals = {int(item['id']): item for item in json.loads(row[0])} if row else {}
    eligible = []
    from .payment_v02 import service_active_in_period
    for item in items:
        service = item['row']
        runtime = conn.execute('SELECT status FROM service_runtime_v0212 WHERE service_id=?', (service['id'],)).fetchone()
        if (not runtime or runtime['status'] == 'active') and service_active_in_period(service, period):
            eligible.append(item)
    if create and (originals or any(stored_schedule_mode(item['row']) == 'specified' for item in eligible)):
        for item in eligible:
            service = item['row']
            if int(service['id']) not in originals:
                runtime = conn.execute('SELECT deferred_until_period FROM service_runtime_v0212 WHERE service_id=?', (service['id'],)).fetchone()
                originals[int(service['id'])] = {'id': int(service['id']),
                    'last_payment_date': service['last_payment_date'], 'next_payment_date': service['next_payment_date'],
                    'next_payment_period': service['next_payment_period'],
                    'deferred_until_period': runtime[0] if runtime else ''}
        if originals:
            conn.execute('''INSERT INTO payment_date_preparations(customer_id,period,items_json) VALUES(?,?,?)
                ON CONFLICT(customer_id,period) DO UPDATE SET items_json=excluded.items_json''',
                (customer_id, period, json.dumps(list(originals.values()), ensure_ascii=False)))
    remaining = []
    total = 0
    for item in eligible:
        service = item['row']
        if stored_schedule_mode(service) != 'specified':
            continue
        total += 1
        original = originals.get(int(service['id']))
        current = readable_date(service['next_payment_date'])
        previous = readable_date(original['next_payment_date']) if original else None
        if original is None or current is None or current == previous:
            remaining.append({'service_id': int(service['id']),
                'title': service['number'] or service['account'] or service['service_type'] or str(service['id'])})
    return {'total': total, 'remaining': remaining, 'originals': originals}


def clear_date_preparation(conn, customer_id, period):
    conn.execute('DELETE FROM payment_date_preparations WHERE customer_id=? AND period=?', (customer_id, period))
