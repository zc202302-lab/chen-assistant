"""Bounded OOXML editing; requires neither Excel nor an external helper."""
from __future__ import annotations

import hashlib
import io
import os
import posixpath
import random
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from xml.sax.saxutils import quoteattr

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
RNS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
HEADERS = ['集团编码', '角色类型', '手机号码', '姓名', '人工识别', '部门']
TAG = lambda name: f'{{{NS}}}{name}'


def _xml(data):
    if b'<!DOCTYPE' in data.replace(b'\x00', b'').upper() or b'<!ENTITY' in data.replace(b'\x00', b'').upper():
        raise ValueError('Excel包含不支持的XML定义')
    return ET.fromstring(data)


def _serialize(root, original):
    # Keep lexical namespace prefixes used by mc:Ignorable and extension attributes.
    namespaces = dict(item for _, item in ET.iterparse(io.BytesIO(original), events=['start-ns']))
    for prefix, uri in namespaces.items():
        if not re.fullmatch(r'ns\d+', prefix):
            ET.register_namespace(prefix, uri)
    result = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    start = result.index(b'<', result.index(b'?>') + 2)
    end = result.index(b'>', start)
    missing = []
    for prefix, uri in namespaces.items():
        name = 'xmlns' + (':' + prefix if prefix else '')
        if (name + '=').encode() not in result[start:end]:
            missing.append(f' {name}={quoteattr(uri)}')
    return result[:end] + ''.join(missing).encode() + result[end:]


def _package(data):
    if len(data) > 20 * 1024 * 1024:
        raise ValueError('目标Excel超过20MB，请清理模板后重试')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > 4000 or len({i.filename for i in infos}) != len(infos) or sum(i.file_size for i in infos) > 64 * 1024 * 1024:
            raise ValueError('目标Excel过大或损坏')
        parts = {i.filename: archive.read(i) for i in infos}
    book = _xml(parts['xl/workbook.xml'])
    rels = _xml(parts['xl/_rels/workbook.xml.rels'])
    sheets = book.find(TAG('sheets'))
    if sheets is None or not len(sheets):
        raise ValueError('目标Excel没有工作表')
    sheet_id = sheets[0].get(f'{{{RNS}}}id')
    link = next((r for r in rels if r.get('Id') == sheet_id and r.get('TargetMode') != 'External'), None)
    if link is None:
        raise ValueError('目标Excel工作表关系无效')
    target = link.get('Target', '')
    path = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
    if not path.startswith('xl/worksheets/') or path not in parts:
        raise ValueError('目标Excel第一张表不可用')
    return parts, path


def _value(cell, shared):
    if cell is None:
        return ''
    if cell.get('t') == 'inlineStr':
        return ''.join(t.text or '' for t in cell.iter(TAG('t')))
    node = cell.find(TAG('v'))
    value = node.text or '' if node is not None else ''
    return shared[int(value)] if cell.get('t') == 's' else value


def _headers(parts, root):
    shared = []
    if 'xl/sharedStrings.xml' in parts:
        shared = [''.join(t.text or '' for t in item.iter(TAG('t'))) for item in _xml(parts['xl/sharedStrings.xml'])]
    row = root.find(f"{TAG('sheetData')}/{TAG('row')}[@r='1']")
    cells = {c.get('r'): c for c in row} if row is not None else {}
    if [_value(cells.get(f'{col}1'), shared).strip() for col in 'ABCDEF'] != HEADERS:
        raise ValueError('目标文件第一张表A至F列表头不匹配，请选择“批量添加集团成员.xlsx”')
    return row


def _validate_values(numbers, groups, role, manual):
    if not isinstance(numbers, list) or not 1 <= len(numbers) <= 5000 or any(not isinstance(n, str) or not re.fullmatch(r'\d{5,20}', n, flags=re.ASCII) for n in numbers):
        raise ValueError('号码必须为5至20位数字，且一次1至5000个')
    if not isinstance(groups, list) or not 1 <= len(groups) <= 5000:
        raise ValueError('请先上传有效集团模板')
    if any(not isinstance(v, str) or not v.strip() or len(v) > 128 or re.search(r'[\x00-\x1f\ud800-\udfff\ufffe\uffff]', v) for v in [*groups, role, manual]):
        raise ValueError('集团编码或默认值无效')


def build_workbook(original, numbers, groups, role, manual, choose=None):
    _validate_values(numbers, groups, role, manual)
    parts, path = _package(original)
    root = _xml(parts[path])
    _headers(parts, root)
    if root.find(TAG('sheetProtection')) is not None or any('/tables/' in name for name in parts):
        raise ValueError('目标模板有工作表保护或Excel表格对象，请解除后重试')
    # Comments, drawings and embedded objects can carry stale data outside cells.
    if any(root.find(TAG(tag)) is not None for tag in ('drawing', 'legacyDrawing', 'oleObjects', 'extLst')):
        raise ValueError('目标模板含批注、图形或扩展对象，请使用纯表格模板')
    data = root.find(TAG('sheetData'))
    rows = {int(row.get('r', '0')): row for row in data}
    if any(n < 1 or n > 100000 for n in rows):
        raise ValueError('目标模板行范围无效或过大')
    sample = rows.get(2)
    styles = {re.sub(r'\d+$', '', c.get('r', '')): c.get('s') for c in sample} if sample is not None else {}
    for n, row in rows.items():
        if n > 1:
            for cell in row:
                for node in list(cell):
                    cell.remove(node)
                cell.attrib.pop('t', None)
    merges = root.find(TAG('mergeCells'))
    if merges is not None:
        for merge in list(merges):
            coords = re.findall(r'\d+', merge.get('ref', ''))
            if len(coords) != 2:
                raise ValueError('模板合并单元格无效')
            first, last = map(int, coords)
            if first <= 1 < last:
                raise ValueError('表头不能与数据行合并')
            if last > 1:
                merges.remove(merge)
        if len(merges):
            merges.set('count', str(len(merges)))
        else:
            root.remove(merges)
    hyperlinks = root.find(TAG('hyperlinks'))
    if hyperlinks is not None:
        for item in list(hyperlinks):
            if any(int(n) > 1 for n in re.findall(r'\d+', item.get('ref', ''))):
                hyperlinks.remove(item)
        if not len(hyperlinks):
            root.remove(hyperlinks)
    choose = choose or random.SystemRandom().choice
    expected = []
    for n, number in enumerate(numbers, 2):
        row = rows.get(n)
        if row is None:
            attrs = dict(sample.attrib) if sample is not None else {}
            attrs.update(r=str(n))
            attrs.pop('spans', None)
            row = ET.Element(TAG('row'), attrs)
            rows[n] = row
        values = {'A': choose(groups), 'B': role, 'C': number, 'E': manual}
        expected.append(values)
        cells = {re.sub(r'\d+$', '', c.get('r', '')): c for c in row}
        for col, value in values.items():
            cell = cells.get(col)
            if cell is None:
                cell = ET.SubElement(row, TAG('c'), r=f'{col}{n}')
                if styles.get(col) is not None:
                    cell.set('s', styles[col])
            cell.set('t', 'inlineStr')
            text = ET.SubElement(ET.SubElement(cell, TAG('is')), TAG('t'))
            text.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
            text.text = value
        row[:] = sorted(row, key=lambda c: (len(re.sub(r'\d+$', '', c.get('r', ''))), c.get('r', '')))
    data[:] = [rows[n] for n in sorted(rows)]
    dimension = root.find(TAG('dimension'))
    if dimension is not None:
        columns = [re.sub(r'\d+$', '', c.get('r', 'F')) for row in rows.values() for c in row]
        last_column = max(['F', *columns], key=lambda col: (len(col), col))
        dimension.set('ref', f'A1:{last_column}{max(rows)}')
    parts[path] = _serialize(root, parts[path])
    # All formulas below the header have been removed; invalidate calculation caches.
    if 'xl/calcChain.xml' in parts:
        del parts['xl/calcChain.xml']
        for name in ('xl/_rels/workbook.xml.rels', '[Content_Types].xml'):
            document = _xml(parts[name])
            for node in list(document):
                if 'calcChain' in node.get('Type', '') or 'calcChain' in node.get('PartName', ''):
                    document.remove(node)
            parts[name] = _serialize(document, parts[name])
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    result = output.getvalue()
    verified, verified_path = _package(result)
    check = _xml(verified[verified_path])
    _headers(verified, check)
    for row in check.find(TAG('sheetData')):
        n = int(row.get('r'))
        if n == 1:
            continue
        wanted = expected[n - 2] if n - 2 < len(expected) else {}
        actual = {re.sub(r'\d+$', '', c.get('r', '')): _value(c, []) for c in row if _value(c, [])}
        if actual != wanted or any(c.find(TAG('f')) is not None for c in row):
            raise ValueError('写入校验失败，原文件未修改')
    return result


@contextmanager
def file_lock(target):
    with open(str(target) + '.lock', 'a+b') as stream:
        stream.seek(0)
        if stream.read(1) == b'':
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError('正在执行另一批写入，请稍后重试')
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _stage(target, content):
    handle, name = tempfile.mkstemp(prefix='.' + target.stem + '-', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        return Path(name)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def write_batch(target, numbers, groups, role, manual):
    _validate_values(numbers, groups, role, manual)
    target = Path(target)
    if target.suffix.lower() != '.xlsx' or not target.is_file() or target.is_symlink():
        raise ValueError('请选择已存在的“批量添加集团成员.xlsx”；XLS请先另存为XLSX')
    staged = backup_stage = None
    try:
        with file_lock(target):
            if target.stat().st_size > 20 * 1024 * 1024:
                raise ValueError('目标Excel超过20MB')
            original = target.read_bytes()
            content = build_workbook(original, numbers, groups, role, manual)
            staged = _stage(target, content)
            if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(original).digest():
                raise ValueError('文件在写入期间被修改，请关闭Excel后重试')
            backup = target.with_name(target.stem + '.备份.xlsx')
            backup_stage = _stage(backup, original)
            os.replace(backup_stage, backup)
            backup_stage = None
            os.replace(staged, target)
            staged = None
        return {'ok': True, 'count': len(numbers), 'path': str(target), 'backup': str(backup)}
    except PermissionError:
        raise ValueError('无法写入文件，请关闭Excel并确认文件夹可写，然后重新点击批量添加')
    finally:
        for path in (staged, backup_stage):
            if path:
                path.unlink(missing_ok=True)
