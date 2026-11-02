"""Local Windows rules; the server only supplies the account master gate."""
from dataclasses import asdict
import re
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))


def validate_local_policy(raw):
    keys = ('enabled', 'instant', 'scheduled')
    if any(type(raw.get(key)) is not bool for key in keys):
        raise ValueError('提醒开关无效')
    if raw['enabled'] and not (raw['instant'] or raw['scheduled']):
        raise ValueError('请至少选择一种提醒方式')
    times = raw.get('times')
    if not isinstance(times, list) or len(times) > 12 or any(
            not isinstance(t, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', t) for t in times):
        raise ValueError('时间应为 HH:MM，最多12个')
    if len(set(times)) != len(times):
        raise ValueError('提醒时间不能重复')
    days = raw.get('weekdays')
    if not isinstance(days, list) or not days or any(type(d) is not int or d not in range(7) for d in days) or len(set(days)) != len(days):
        raise ValueError('请选择有效的重复日期')
    categories = raw.get('categories')
    expected = ('number_inbox', 'task', 'task_global', 'task_customer')
    if not isinstance(categories, dict) or any(type(categories.get(k)) is not bool for k in expected):
        raise ValueError('通知类别无效')
    if categories['task'] and not (categories['task_global'] or categories['task_customer']):
        raise ValueError('请至少选择一种待办来源')
    return {**{k: raw[k] for k in keys}, 'times': sorted(times), 'weekdays': sorted(days),
            'categories': {k: categories[k] for k in expected}}


def effective_policy(local, remote):
    policy = asdict(local)
    # Ignore every remote field except the master gate, including old v0.5.20 feeds.
    policy['enabled'] = bool(local.enabled and (remote is None or
        (isinstance(remote, dict) and remote.get('enabled') is True)))
    return policy


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


def task_alert_decision(payload, notified, last_slot, now=None, *, local=None):
    """Return visible due tasks and one alert decision without importing Tk."""
    policy = payload.get('reminder_policy')
    if local is not None:
        policy = effective_policy(local, policy)
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
