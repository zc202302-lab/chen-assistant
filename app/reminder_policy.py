"""Account reminder rules shared by Web Push and scoped desktop feeds."""
import json

DEFAULT_DAYS = list(range(7))
DAY_KEY = 'reminder_schedule_weekdays'


def schedule_weekdays(conn):
    row = conn.execute('SELECT value FROM app_meta WHERE key=?', (DAY_KEY,)).fetchone()
    try:
        value = json.loads(row['value']) if row else DEFAULT_DAYS
        if not isinstance(value, list) or not value or any(type(day) is not int or day not in DEFAULT_DAYS for day in value) or len(set(value)) != len(value):
            return DEFAULT_DAYS[:]
        return sorted(value)
    except (ValueError, TypeError):
        return DEFAULT_DAYS[:]


def task_scope(event_key):
    return 'task_global' if event_key.startswith('work-task:') else 'task_customer'


def notification_allowed(prefs, kind, event_key):
    if not prefs.get('all', True):
        return False
    if event_key.startswith('test:'):
        return True
    if event_key.startswith('scheduled:'):
        return prefs.get('scheduled', True)
    return (prefs.get('instant', True) and prefs.get(kind, True)
            and (kind != 'task' or prefs.get(task_scope(event_key), True)))


def desktop_policy(conn):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='reminder_preferences'").fetchone():
        return None
    prefs = {r['kind']: bool(r['enabled']) for r in conn.execute('SELECT * FROM reminder_preferences')}
    return {'enabled': prefs.get('all', True)}


def customer_task_alerts(conn, now):
    alerts = []
    for row in conn.execute("SELECT t.id,t.title,t.customer_id,t.remind_at,t.remind_date,c.name customer_name FROM tasks t JOIN customers c ON c.id=t.customer_id WHERE t.done=0"):
        value = row['remind_at'] or (row['remind_date'] + 'T09:00' if row['remind_date'] else '')
        if value and value <= now:
            alerts.append({'id': row['id'], 'source': 'customer', 'title': row['customer_name'] + ' · ' + row['title'],
                           'remind_at': value, 'due': True, 'url': f"/customers/{row['customer_id']}?tab=tasks"})
    return alerts
