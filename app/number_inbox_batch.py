"""Group template settings and signed, path-free desktop batch requests."""
import hashlib
import hmac
import json
import re
import secrets
import time

from .work_list_excel import ExcelTable, NS

META_KEY = 'number_inbox_group_batch_v1'
MAX_NUMBERS = 5000


def settings(conn):
    row = conn.execute('SELECT value FROM app_meta WHERE key=?', (META_KEY,)).fetchone()
    raw = json.loads(row['value']) if row else {}
    return {'groups': raw.get('groups', []), 'filename': raw.get('filename', ''),
            'role': raw.get('role', 'MemberSort0102'), 'manual': raw.get('manual', '1')}


def field(value):
    value = value.strip()
    if not value or len(value) > 128 or re.search(r'[\x00-\x1f\ud800-\udfff\ufffe\uffff]', value):
        raise ValueError('B、E列默认值不能为空，且最多128个字符')
    return value


def read_groups(content, filename):
    table = ExcelTable(content, filename)
    try:
        name = table.sheets[0]
        rows = table.read(name, 1, 'A', 'A')['rows']
        if table.zip:
            for cell in table._xml(table.paths[name]).findall(f'{{{NS}}}sheetData/{{{NS}}}row/{{{NS}}}c'):
                if not re.fullmatch(r'A(?:[2-9]|[1-9]\d+)', cell.get('r', '')):
                    continue
                if cell.find(f'{{{NS}}}f') is not None:
                    raise ValueError('集团编码请使用固定文本，不支持公式')
                value = cell.find(f'{{{NS}}}v')
                if cell.get('t', 'n') == 'n' and value is not None and len(re.sub(r'\D', '', value.text or '')) > 15:
                    raise ValueError('超过15位的集团编码请在原表中保存为文本后上传')
        elif table.xls:
            import xlrd
            sheet = table.xls.sheet_by_name(name)
            for item in rows:
                cell = sheet.cell(item['row'] - 1, 0)
                if cell.ctype == xlrd.XL_CELL_NUMBER and abs(cell.value) >= 10 ** 15:
                    raise ValueError('超过15位的集团编码请在原表中保存为文本后上传')
        groups = list(dict.fromkeys(field(row['cells'][0]) for row in rows if row['cells'][0].strip()))
        if not groups:
            raise ValueError('集团模板第一张表A列第二行起没有集团编码')
        return groups
    finally:
        table.close()


def signed_batch(numbers, saved, token):
    if not numbers:
        raise ValueError('目前没有未加号码，未清空本地文件')
    if len(numbers) > MAX_NUMBERS:
        raise ValueError('一次最多5000个号码，请先处理部分号码后重试')
    if not saved['groups']:
        raise ValueError('请先在设置中上传集团模板')
    payload = {'version': 1, 'nonce': secrets.token_hex(16), 'issued_at': int(time.time()),
               'groups': saved['groups'], 'numbers': numbers,
               'role': saved['role'], 'manual': saved['manual']}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    if len(canonical) > 900 * 1024:
        raise ValueError('集团模板内容过大，请缩短编码或减少集团后重试')
    return {'payload': payload, 'signature': hmac.new(token.encode(), canonical, hashlib.sha256).hexdigest()}


RETENTION_SECONDS = 5 * 86400
BATCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS number_inbox_batches (
    nonce TEXT PRIMARY KEY,
    request_signature TEXT NOT NULL,
    item_ids TEXT NOT NULL,
    issued_at INTEGER NOT NULL,
    completed_at INTEGER
);
"""


def register_batch(conn, signed, item_ids):
    conn.execute('INSERT INTO number_inbox_batches(nonce,request_signature,item_ids,issued_at) VALUES(?,?,?,?)',
                 (signed['payload']['nonce'], signed['signature'], json.dumps(item_ids), signed['payload']['issued_at']))


def complete_batch(conn, body, token, now=None):
    from datetime import datetime, timezone
    now = time.time() if now is None else now
    if not isinstance(body, dict) or set(body) != {'receipt', 'signature'}:
        raise ValueError('写入回执格式无效')
    receipt, signature = body['receipt'], body['signature']
    if not isinstance(receipt, dict) or set(receipt) != {'nonce', 'request_signature', 'count', 'completed_at'}:
        raise ValueError('写入回执格式无效')
    canonical = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    expected = hmac.new(token.encode(), b'number-batch-complete-v1\n' + canonical, hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise ValueError('写入回执校验失败')
    if not isinstance(receipt['nonce'], str) or not re.fullmatch('[a-f0-9]{32}', receipt['nonce']):
        raise ValueError('批次编号无效')
    row = conn.execute('SELECT * FROM number_inbox_batches WHERE nonce=?', (receipt['nonce'],)).fetchone()
    if not row or row['request_signature'] != receipt['request_signature']:
        raise ValueError('批次不存在或已过期')
    ids = json.loads(row['item_ids'])
    if type(receipt['count']) is not int or receipt['count'] != len(ids):
        raise ValueError('写入数量与批次不一致')
    completed = receipt['completed_at']
    if type(completed) is not int or not row['issued_at'] - 60 <= completed <= now + 60:
        raise ValueError('写入回执时间无效')
    # Replayed successful receipts do not restart retention or change later submissions.
    if row['completed_at'] is not None:
        return {'ok': True, 'count': len(ids), 'archived': True}
    stamp = datetime.fromtimestamp(completed, timezone.utc).isoformat(timespec='seconds')
    conn.executemany("UPDATE number_inbox SET status='done',completed_at=? WHERE id=? AND status='pending'",
                     [(stamp, item_id) for item_id in ids])
    conn.execute('UPDATE number_inbox_batches SET completed_at=? WHERE nonce=?', (completed, receipt['nonce']))
    purge_expired(conn, now)
    return {'ok': True, 'count': len(ids), 'archived': True}


def purge_expired(conn, now=None):
    now = time.time() if now is None else now
    # ISO timestamps may contain UTC offsets; SQLite julianday normalizes them.
    cutoff = 2440587.5 + (now - RETENTION_SECONDS) / 86400
    conn.execute("DELETE FROM number_inbox WHERE status='done' AND completed_at<>'' AND julianday(completed_at)<=?", (cutoff,))
    conn.execute('DELETE FROM number_inbox_batches WHERE COALESCE(completed_at,issued_at)<=?', (now - RETENTION_SECONDS,))


async def retention_worker(stop):
    import asyncio
    import logging
    from .db import db
    while not stop.is_set():
        try:
            with db() as conn:
                purge_expired(conn)
        except Exception:
            logging.getLogger(__name__).exception('Number inbox retention cleanup failed')
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
