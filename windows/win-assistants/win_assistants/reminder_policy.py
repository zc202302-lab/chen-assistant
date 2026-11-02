"""Read shared account rules without granting module tokens settings-write rights."""
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))


def allows(policy, kind, scope=None):
    if policy is None:
        return True
    if not isinstance(policy, dict):
        return False
    categories = policy.get('categories', {})
    return bool(policy.get('enabled', False) and categories.get(kind, False)
                and (scope is None or categories.get(scope, False)))


def scheduled_key(policy, now=None):
    if not isinstance(policy, dict) or not policy.get('enabled') or not policy.get('scheduled'):
        return ''
    now = now or datetime.now(TZ)
    if now.tzinfo is not None:
        now = now.astimezone(TZ)
    minute = now.strftime('%H:%M')
    if now.weekday() not in policy.get('weekdays', []) or minute not in policy.get('times', []):
        return ''
    return now.strftime('%Y-%m-%d:') + minute


def task_alert_decision(payload, notified, last_slot, now=None):
    """Return visible due tasks and one alert decision without importing Tk."""
    policy = payload.get('reminder_policy')
    all_due = [dict(item, source='global') for item in payload['items'] if item['due']]
    all_due.extend(payload.get('customer_task_reminders', []))
    identity = lambda item: (item.get('source', 'global'), item['id'], item['remind_at'])
    all_current = {identity(item) for item in all_due}
    due = [item for item in all_due if allows(policy, 'task',
           'task_customer' if item.get('source') == 'customer' else 'task_global')]
    current = {identity(item) for item in due}
    notified.intersection_update(all_current)
    fresh = current - notified
    notified.update(all_current)
    slot = scheduled_key(policy, now)
    timed = bool(slot and slot != last_slot and due)
    alert = bool(due and ((fresh and (policy is None or policy.get('instant'))) or timed))
    return due, alert, slot if timed else last_slot
