from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import calendar
import sqlite3

from fastapi import HTTPException
from .db import now_iso


def current_period() -> str:
    return date.today().strftime('%Y-%m')


def add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def add_periods(period: str, months: int) -> str:
    try:
        y, m = [int(x) for x in period[:7].split('-')]
    except Exception:
        return ''
    idx = y * 12 + (m - 1) + months
    return f'{idx // 12:04d}-{idx % 12 + 1:02d}'


def cycle_months(text: str) -> int | None:
    s = (text or '').strip()
    if not s:
        return None
    if s in {'月', '每月', '1个月'}:
        return 1
    if s in {'季度', '季', '3个月'}:
        return 3
    if s in {'半年', '6个月'}:
        return 6
    if s in {'年', '每年', '12个月'}:
        return 12
    if s.endswith('个月'):
        try:
            n = int(s[:-2])
            return n if n > 0 else None
        except Exception:
            return None
    return None


def service_interval_months(row) -> int | None:
    if 'payment_interval_months' in row.keys():
        try:
            explicit = int(row['payment_interval_months'] or 0)
        except Exception:
            explicit = 0
        if explicit > 0:
            return explicit
    return cycle_months(row['payment_cycle'])


def service_is_due(row, today: date | None = None) -> bool:
    """Whether this service belongs in the current payment workbench.

    Monthly services are always due. For longer cycles, v0.2.5 prefers the explicit
    next_payment_period. A missed due month remains due (current >= next), so an overdue
    service can never silently disappear just because the calendar moved forward.
    """
    today = today or date.today()
    months = service_interval_months(row)
    if months is None:
        return False
    if months == 1:
        return True

    if 'next_payment_period' in row.keys():
        next_period = (row['next_payment_period'] or '').strip()
        if next_period:
            return today.strftime('%Y-%m') >= next_period

    last = (row['last_payment_date'] or '').strip()
    if not last:
        return True
    try:
        last_d = date.fromisoformat(last[:10])
    except Exception:
        return True
    return add_months(last_d, months) <= today


def next_due_after_payment(row, paid_period: str) -> str:
    months = service_interval_months(row)
    if not months or months == 1:
        return ''
    current_next = (row['next_payment_period'] or '').strip() if 'next_payment_period' in row.keys() else ''
    base = current_next or paid_period
    nxt = base
    while nxt and nxt <= paid_period:
        nxt = add_periods(nxt, months)
    return nxt or add_periods(paid_period, months)


def service_active_in_period(row, period: str) -> bool:
    start = (row['active_from_period'] or '').strip() if 'active_from_period' in row.keys() else ''
    stop = (row['inactive_from_period'] or '').strip() if 'inactive_from_period' in row.keys() else ''
    if start and period < start:
        return False
    if stop and period >= stop:
        return False
    return True


def customer_is_due(conn: sqlite3.Connection, customer_id: int) -> bool:
    period = current_period()
    rows = conn.execute('SELECT * FROM services WHERE customer_id=?', (customer_id,)).fetchall()
    return any(service_active_in_period(r, period) and service_is_due(r) for r in rows)


def effective_status(customer):
    same = customer['payment_period'] == current_period()
    return {
        'notified': int(customer['notified']) if same else 0,
        'completed': int(customer['completed']) if same else 0,
    }


def effective_payment_rule(conn: sqlite3.Connection, service_id: int, period: str, fallback_service=None):
    row = conn.execute(
        '''SELECT * FROM service_payment_rules
           WHERE service_id=? AND effective_period<=?
           ORDER BY effective_period DESC, id DESC LIMIT 1''',
        (service_id, period),
    ).fetchone()
    if row:
        return {'mode': row['mode'], 'fixed_amount': float(row['fixed_amount'] or 0), 'effective_period': row['effective_period']}
    fixed = bool(fallback_service and fallback_service['fixed_fee'])
    return {
        'mode': 'fixed' if fixed else 'variable',
        'fixed_amount': float((fallback_service['monthly_fee'] if fallback_service else 0) or 0),
        'effective_period': '1900-01',
    }


def _previous_amount(conn: sqlite3.Connection, service_id: int, period: str, fallback: float) -> float:
    row = conn.execute(
        '''SELECT amount FROM payment_entries
           WHERE service_id=? AND period<? ORDER BY period DESC, id DESC LIMIT 1''',
        (service_id, period),
    ).fetchone()
    return float(row['amount']) if row else float(fallback or 0)


def ensure_payment_entry(conn: sqlite3.Connection, service, period: str):
    existing = conn.execute(
        'SELECT * FROM payment_entries WHERE service_id=? AND period=?',
        (service['id'], period),
    ).fetchone()
    rule = effective_payment_rule(conn, service['id'], period, service)

    if existing and rule['mode'] == 'fixed':
        desired = float(rule['fixed_amount'])
        if (not bool(existing['confirmed'])) or abs(float(existing['amount'] or 0) - desired) >= 0.005 or existing['source'] != 'fixed':
            reference = existing['reference_amount']
            if reference is None:
                reference = float(existing['amount'] or 0)
            conn.execute(
                '''UPDATE payment_entries
                   SET amount=?,reference_amount=?,source='fixed',confirmed=1,updated_at=?
                   WHERE id=?''',
                (desired, reference, now_iso(), existing['id']),
            )
            existing = conn.execute('SELECT * FROM payment_entries WHERE id=?', (existing['id'],)).fetchone()
        return existing, rule

    if existing:
        return existing, rule

    inherited = _previous_amount(conn, service['id'], period, float(service['monthly_fee'] or 0))
    amount = float(rule['fixed_amount']) if rule['mode'] == 'fixed' else inherited
    confirmed = 1 if rule['mode'] == 'fixed' else 0
    source = 'fixed' if rule['mode'] == 'fixed' else 'inherited'
    now = now_iso()
    conn.execute(
        '''INSERT INTO payment_entries
           (service_id,period,amount,reference_amount,source,confirmed,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?)''',
        (service['id'], period, amount, inherited, source, confirmed, now, now),
    )
    row = conn.execute(
        'SELECT * FROM payment_entries WHERE service_id=? AND period=?',
        (service['id'], period),
    ).fetchone()
    return row, rule


def payment_snapshot(conn: sqlite3.Connection, customer_id: int, period: str | None = None):
    period = period or current_period()
    rows = conn.execute(
        '''SELECT s.*, g.name invoice_group_name
           FROM services s
           LEFT JOIN invoice_groups g ON g.id=s.invoice_group_id
           WHERE s.customer_id=?
           ORDER BY CASE WHEN COALESCE(s.sort_order,0)>0 THEN s.sort_order ELSE 100000000+s.id END,
                    s.source_row,s.id''',
        (customer_id,),
    ).fetchall()
    items = []
    required = pending = changed = zero = 0
    total = 0.0
    due_count = 0
    for s in rows:
        if not service_active_in_period(s, period):
            continue
        due_now = service_is_due(s)
        existing = conn.execute(
            'SELECT * FROM payment_entries WHERE service_id=? AND period=?',
            (s['id'], period),
        ).fetchone()
        # The v0.1 bootstrap created imported rows for every service. Those rows alone must
        # not make a non-due service appear. A real current-period row (inherited/manual/fixed)
        # stays visible after payment completion advances the next due period.
        worked_this_period = bool(existing and existing['source'] != 'imported')
        if not due_now and not worked_this_period:
            continue
        due_count += 1
        pe, rule = ensure_payment_entry(conn, s, period)
        amount = float(pe['amount'] or 0)
        reference = pe['reference_amount']
        confirmed = bool(pe['confirmed'])
        delta = None
        if confirmed and reference is not None:
            diff = round(amount - float(reference), 2)
            if abs(diff) >= 0.005:
                delta = diff
        if rule['mode'] == 'variable':
            required += 1
            if not confirmed:
                pending += 1
        if delta is not None:
            changed += 1
        if confirmed and abs(amount) < 0.005:
            zero += 1
        total += amount
        items.append({
            'row': s,
            'payment': pe,
            'rule': rule,
            'delta': delta,
            'invoice_group_name': s['invoice_group_name'] or '',
        })
    return items, {
        'due_count': due_count,
        'required': required,
        'pending': pending,
        'changed': changed,
        'zero': zero,
        'total': round(total, 2),
        'txt_ready': pending == 0,
    }


def parse_money(value: str) -> float:
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise HTTPException(400, '金额格式不正确')
    if not amount.is_finite() or amount < 0:
        raise HTTPException(400, '金额必须是大于等于0的数字')
    return float(amount.quantize(Decimal('0.01')))


def format_fee(value: float) -> str:
    v = round(float(value or 0), 2)
    if float(v).is_integer():
        return str(int(v))
    return f'{v:.2f}'.rstrip('0').rstrip('.')


def valid_invoice_group(conn: sqlite3.Connection, customer_id: int, raw: str) -> int | None:
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        gid = int(raw)
    except Exception:
        raise HTTPException(400, '开票分组无效')
    row = conn.execute('SELECT id FROM invoice_groups WHERE id=? AND customer_id=?', (gid, customer_id)).fetchone()
    if not row:
        raise HTTPException(400, '开票分组不属于该客户')
    return gid
