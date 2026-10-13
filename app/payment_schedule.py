"""Free-text payment dates with explicit, month-based reminder semantics."""
from datetime import date
import calendar
import re


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
    value = service['next_payment_date']
    if value is None:
        return computed_next_date(service['last_payment_date'], service['payment_interval_months'])
    return str(value).strip()


def explicit_due(service, period):
    """None means no override; unknown text stays visible to avoid missed reminders."""
    raw = explicit_payment_date(service)
    if not raw:
        return None
    parsed = readable_date(raw)
    return True if parsed is None else period >= parsed.strftime('%Y-%m')


def ensure_payment_date_schema(conn=None):
    if conn is None:
        from .db import db
        with db() as owned:
            ensure_payment_date_schema(owned)
        return
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(services)')}
    if 'next_payment_date' not in columns:
        conn.execute('ALTER TABLE services ADD COLUMN next_payment_date TEXT DEFAULT NULL')
    for row in conn.execute('SELECT id,last_payment_date,payment_interval_months FROM services WHERE next_payment_date IS NULL').fetchall():
        value = computed_next_date(row['last_payment_date'], row['payment_interval_months'])
        conn.execute('UPDATE services SET next_payment_date=? WHERE id=?', (value, row['id']))
