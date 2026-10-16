"""Shared number validation and atomic pending-inbox submission."""
import re
import secrets

from fastapi import HTTPException
from .db import now_iso


def normalize_number(value: str) -> tuple[str, str]:
    raw = (value or '').strip()
    if len(raw) > 64:
        raise HTTPException(400, '号码过长')
    digits = re.sub(r'\D', '', raw)
    if digits.startswith('86') and len(digits) == 13:
        digits = digits[2:]
    if len(digits) < 5 or len(digits) > 20:
        raise HTTPException(400, '请输入有效号码')
    return raw, digits


def collect_numbers(conn, normalized: list[str]) -> dict:
    """Borrow a connection; its owner commits or rolls back the whole batch."""
    batch = secrets.token_urlsafe(24)
    submitted_at = now_iso()
    added = 0
    for digits in dict.fromkeys(normalized):
        added += conn.execute(
            """INSERT OR IGNORE INTO number_inbox
               (number,normalized_number,submitter,note,status,submitted_at,completed_at,submit_batch)
               VALUES(?,?, '', '', 'pending', ?, '', ?)""",
            (digits, digits, submitted_at, batch),
        ).rowcount
    return {'batch': batch, 'received': len(normalized), 'added': added,
            'duplicates': len(normalized) - added}
