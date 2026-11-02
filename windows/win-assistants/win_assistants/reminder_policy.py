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
