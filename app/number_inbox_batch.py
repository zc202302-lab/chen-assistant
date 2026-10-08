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
