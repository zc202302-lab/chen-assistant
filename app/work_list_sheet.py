"""Spreadsheet presentation and transactional editing of existing work-list records."""
from __future__ import annotations

import io
import json
import re
from datetime import datetime

import xlsxwriter
from fastapi import HTTPException
from starlette.datastructures import FormData

from .db import now_iso

MAX_ROWS = 5000
MAX_COLS = 50


def ensure_sheet_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS work_list_layouts (
        list_id INTEGER PRIMARY KEY REFERENCES work_lists(id) ON DELETE CASCADE,
        layout_json TEXT NOT NULL DEFAULT '{}')''')


def get_layout(conn, list_id):
    row = conn.execute('SELECT layout_json FROM work_list_layouts WHERE list_id=?', (list_id,)).fetchone()
    return json.loads(row['layout_json']) if row else {}


def put_layout(conn, list_id, layout):
    conn.execute('''INSERT INTO work_list_layouts(list_id,layout_json) VALUES(?,?)
        ON CONFLICT(list_id) DO UPDATE SET layout_json=excluded.layout_json''',
        (list_id, json.dumps(layout, ensure_ascii=False)))


def _bounded_number(value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum:
        raise HTTPException(400, '行列尺寸或单元格格式无效')
    return round(value, 2)


def clean_style(raw):
    if not isinstance(raw, dict):
        raise HTTPException(400, '单元格格式无效')
    result = {}
    for key in ('bold', 'italic', 'wrap', 'numeric'):
        if key in raw:
            if not isinstance(raw[key], bool):
                raise HTTPException(400, '单元格格式无效')
            result[key] = raw[key]
    for key in ('color', 'background'):
        if key in raw:
            if not isinstance(raw[key], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', raw[key]):
                raise HTTPException(400, '单元格颜色无效')
            result[key] = raw[key]
    if 'font' in raw:
        if not isinstance(raw['font'], str) or not 1 <= len(raw['font']) <= 80:
            raise HTTPException(400, '字体无效')
        result['font'] = raw['font']
    if 'size' in raw:
        result['size'] = _bounded_number(raw['size'], 6, 72)
    for key, allowed in [('align', {'left', 'center', 'right'}), ('valign', {'top', 'center', 'bottom'}),
                         ('underline', {0, 1, 2})]:
        if key in raw:
            if raw[key] not in allowed:
                raise HTTPException(400, '单元格对齐或下划线无效')
            result[key] = raw[key]
    for edge in ('left', 'right', 'top', 'bottom'):
        key = 'border_' + edge
        if key in raw:
            value = raw[key]
            if not isinstance(value, dict) or value.get('style') not in range(0, 14):
                raise HTTPException(400, '单元格边框无效')
            cleaned = {'style': value['style']}
            if value.get('color'):
                cleaned['color'] = clean_style({'color': value['color']})['color']
            result[key] = cleaned
    if 'number_format' in raw:
        value = raw['number_format']
        if not isinstance(value, str) or len(value) > 160:
            raise HTTPException(400, '数字格式无效')
        result['number_format'] = value
    return result


def clean_layout(raw, row_ids, col_ids):
    if not isinstance(raw, dict):
        raise HTTPException(400, '表格布局无效')
    rows, cols = set(row_ids) | {'h'}, set(col_ids)
    result = {'mode': 'grid', 'legacy': bool(raw.get('legacy', False)),
              'widths': {}, 'heights': {}, 'cells': {}, 'merges': []}
    for key, allowed, minimum, maximum in [('widths', cols, 12, 800), ('heights', rows, 12, 500)]:
        values = raw.get(key, {})
        if not isinstance(values, dict) or any(k not in allowed for k in values):
            raise HTTPException(400, '布局包含不存在的行或列')
        result[key] = {k: _bounded_number(v, minimum, maximum) for k, v in values.items()}
    cells = raw.get('cells', {})
    if not isinstance(cells, dict) or len(cells) > (len(row_ids) + 1) * len(col_ids):
        raise HTTPException(400, '单元格格式过多')
    for key, value in cells.items():
        parts = key.split('|')
        if len(parts) != 2 or parts[0] not in rows or parts[1] not in cols:
            raise HTTPException(400, '格式包含不存在的单元格')
        result['cells'][key] = clean_style(value)
    merges = raw.get('merges', [])
    if not isinstance(merges, list) or len(merges) > 1000:
        raise HTTPException(400, '合并区域过多')
    occupied = set()
    row_order, col_order = ['h', *row_ids], list(col_ids)
    for merge in merges:
        if not isinstance(merge, dict):
            raise HTTPException(400, '合并区域无效')
        mr, mc = merge.get('rows', []), merge.get('cols', [])
        if not isinstance(mr, list) or not isinstance(mc, list) or not mr or not mc or any(r not in rows for r in mr) or any(c not in cols for c in mc):
            raise HTTPException(400, '合并区域包含不存在的行列')
        ri, ci = [row_order.index(r) for r in mr], [col_order.index(c) for c in mc]
        if ri != list(range(ri[0], ri[0] + len(ri))) or ci != list(range(ci[0], ci[0] + len(ci))):
            raise HTTPException(400, '合并区域必须连续')
        if 'h' in mr and len(mr) > 1:
            # A header crossing into data would hide editable records.
            raise HTTPException(400, '表头不能与数据行跨行合并')
        area = {(r, c) for r in mr for c in mc}
        if area & occupied:
            raise HTTPException(400, '合并区域重叠')
        occupied |= area
        if len(area) > 1:
            result['merges'].append({'rows': mr, 'cols': mc})
    return result


def snapshot(conn, item, fields, rows):
    visible = [f for f in fields if not f['hidden']]
    layout = get_layout(conn, item['id'])
    col_ids, row_ids = {str(f['id']) for f in visible}, {str(r['id']) for r in rows}
    layout = layout | {
        'widths': {k: v for k, v in layout.get('widths', {}).items() if k in col_ids},
        'heights': {k: v for k, v in layout.get('heights', {}).items() if k in row_ids or k == 'h'},
        'cells': {k: v for k, v in layout.get('cells', {}).items() if k.split('|')[0] in row_ids | {'h'} and k.split('|')[1] in col_ids},
        'merges': [m for m in layout.get('merges', []) if set(m['rows']) <= row_ids | {'h'} and set(m['cols']) <= col_ids],
    }
    return {'title': item['title'], 'revision': item['revision'],
            'fields': [{'id': str(f['id']), 'label': f['label'], 'kind': f['kind'], 'options': f['options']} for f in visible],
            'rows': [{'id': str(r['id']), 'revision': r['revision'],
                      'values': [r['values'].get(str(f['id']), '') for f in visible]} for r in rows],
            'layout': layout | {'legacy': layout.get('legacy', True)}}


def _shape(data):
    if not isinstance(data, dict) or not isinstance(data.get('fields'), list) or not isinstance(data.get('rows'), list):
        raise HTTPException(400, '表格数据无效')
    fields, rows = data['fields'], data['rows']
    if not 1 <= len(fields) <= MAX_COLS or len(rows) > MAX_ROWS:
        raise HTTPException(400, '每张表最多5000行、50列，至少保留一列')
    for group in (fields, rows):
        if any(not isinstance(v, dict) or not isinstance(v.get('id'), str) for v in group):
            raise HTTPException(400, '行列标识无效')
        ids = [v['id'] for v in group]
        if len(ids) != len(set(ids)):
            raise HTTPException(400, '行列标识重复')
        if any(not re.fullmatch(r'\d+|new_[a-zA-Z0-9_]{1,40}', k) for k in ids):
            raise HTTPException(400, '行列标识无效')
    for row in rows:
        if not isinstance(row.get('values'), list) or len(row['values']) != len(fields):
            raise HTTPException(400, '行的单元格数量不一致')
    return fields, rows


def save_grid(conn, list_id, data):
    from .work_lists import _list, _fields, _rows, _revision, _text, _values
    fields, rows = _shape(data)
    item = _list(conn, list_id, True)
    _revision(data.get('revision'), item['revision'])
    old_fields = [f for f in _fields(conn, list_id) if not f['hidden']]
    old_rows = _rows(conn, list_id)
    def ordered_subset(submitted, existing):
        positions = {key: index for index, key in enumerate(existing)}
        kept = [key for key in submitted if not key.startswith('new_')]
        indexes = [positions.get(key, -1) for key in kept]
        return all(index >= 0 for index in indexes) and indexes == sorted(set(indexes))
    old_field_ids = [str(f['id']) for f in old_fields]
    old_row_ids = [str(r['id']) for r in old_rows]
    if not ordered_subset([f['id'] for f in fields], old_field_ids):
        raise HTTPException(409, '列已被更新，请刷新后重试')
    if not ordered_subset([r['id'] for r in rows], old_row_ids):
        raise HTTPException(409, '记录已被更新，请刷新后重试')
    prior_fields = {str(f['id']): f for f in old_fields}
    prior_rows = {str(r['id']): r for r in old_rows}
    if len(_fields(conn, list_id)) + sum(f['id'].startswith('new_') for f in fields) > MAX_COLS:
        raise HTTPException(400, '每张清单最多50列（含隐藏列）')
    for row in rows:
        if row['id'] in prior_rows:
            _revision(row.get('revision'), prior_rows[row['id']]['revision'])
    layout = clean_layout(data.get('layout', {}), [r['id'] for r in rows], [f['id'] for f in fields])
    layout['legacy'] = get_layout(conn, list_id).get('legacy', True)
    title = _text(data.get('title', item['title']), '名称', 200, True)
    field_map, row_map, validated_fields = {}, {}, []
    position = max((f['position'] for f in _fields(conn, list_id)), default=-1) + 1
    for field in fields:
        label = _text(field.get('label'), '列标题', 80, True)
        if field['id'] in prior_fields:
            previous = prior_fields[field['id']]
            conn.execute('UPDATE work_list_fields SET label=? WHERE id=?', (label, previous['id']))
            current = previous | {'label': label}
        else:
            field_id = conn.execute('INSERT INTO work_list_fields(list_id,label,kind,position) VALUES(?,?,?,?)',
                                    (list_id, label, 'text', position)).lastrowid
            position += 1
            current = {'id': field_id, 'label': label, 'kind': 'text', 'hidden': 0, 'options': []}
        field_map[field['id']] = str(current['id'])
        validated_fields.append(current)
    retained_field_ids = set(field_map.values()) | {
        str(f['id']) for f in _fields(conn, list_id) if f['hidden']
    }
    for row in rows:
        previous = prior_rows.get(row['id'])
        form = []
        for field, value in zip(validated_fields, row['values']):
            if isinstance(value, list) and field['kind'] == 'multi':
                form.extend((f'f_{field["id"]}', v) for v in value)
            elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
                form.append((f'f_{field["id"]}', str(value)))
            else:
                raise HTTPException(400, '单元格内容类型无效')
        values = _values(FormData(form), validated_fields, previous['values'] if previous else {})
        values = {key: value for key, value in values.items() if key in retained_field_ids}
        for field, raw in zip(validated_fields, row['values']):
            if field['kind'] == 'text':
                text = str(raw)
                if len(text) > 4000:
                    raise HTTPException(400, '单元格内容不能超过4000字')
                values[str(field['id'])] = text
        now = now_iso()
        if previous:
            record_id = previous['id']
            if values != previous['values']:
                conn.execute('UPDATE work_list_records SET values_json=?,revision=revision+1,updated_at=? WHERE id=? AND list_id=?',
                             (json.dumps(values, ensure_ascii=False), now, record_id, list_id))
        else:
            record_id = conn.execute('INSERT INTO work_list_records(list_id,values_json,created_at,updated_at) VALUES(?,?,?,?)',
                                     (list_id, json.dumps(values, ensure_ascii=False), now, now)).lastrowid
        row_map[row['id']] = str(record_id)
    removed_rows = set(old_row_ids) - {row_id for row_id in row_map if row_id != 'h'}
    if removed_rows:
        conn.executemany('DELETE FROM work_list_records WHERE list_id=? AND id=?',
                         ((list_id, int(row_id)) for row_id in removed_rows))
    removed_fields = set(old_field_ids) - {field_id for field_id in field_map if not field_id.startswith('new_')}
    if removed_fields:
        conn.executemany('DELETE FROM work_list_fields WHERE list_id=? AND id=?',
                         ((list_id, int(field_id)) for field_id in removed_fields))
    row_map['h'] = 'h'
    layout['widths'] = {field_map[k]: v for k, v in layout['widths'].items()}
    layout['heights'] = {row_map[k]: v for k, v in layout['heights'].items()}
    layout['cells'] = {row_map[k.split('|')[0]] + '|' + field_map[k.split('|')[1]]: v for k, v in layout['cells'].items()}
    layout['merges'] = [{'rows': [row_map[r] for r in m['rows']], 'cols': [field_map[c] for c in m['cols']]} for m in layout['merges']]
    previous_layout = get_layout(conn, list_id)
    hidden_ids = {str(f['id']) for f in _fields(conn, list_id) if f['hidden']}
    layout['widths'].update({k: v for k, v in previous_layout.get('widths', {}).items() if k in hidden_ids})
    layout['cells'].update({k: v for k, v in previous_layout.get('cells', {}).items() if k.split('|')[1] in hidden_ids})
    put_layout(conn, list_id, layout)
    conn.execute('UPDATE work_lists SET title=?,revision=revision+1,updated_at=? WHERE id=?',
                 (title, now_iso(), list_id))
    return snapshot(conn, _list(conn, list_id), _fields(conn, list_id), _rows(conn, list_id))


def create_grid(conn, list_id, data):
    fields, rows = _shape(data)
    if any(not f['id'].startswith('new_') for f in fields) or any(not r['id'].startswith('new_') for r in rows):
        raise HTTPException(400, '新表格行列标识无效')
    put_layout(conn, list_id, {'mode': 'grid', 'legacy': False})
    return save_grid(conn, list_id, data | {'revision': 1})


def import_layout(conn, list_id, table, field_ids, row_ids):
    """Map source coordinates to stable record/field IDs, keeping prior layouts on append."""
    previous = get_layout(conn, list_id)
    if previous and previous.get('mode') == 'grid':
        return  # Appending must not replace the existing sheet's layout.
    raw = table.get('layout')
    if not raw:
        return
    cols = {str(k): str(v) for k, v in field_ids.items()}
    rows = {str(k): str(v) for k, v in row_ids.items()} | {str(raw['header']): 'h'}
    layout = {'mode': 'grid', 'legacy': False, 'widths': {}, 'heights': {}, 'cells': {}, 'merges': []}
    layout['widths'] = {cols[k]: v for k, v in raw.get('widths', {}).items() if k in cols}
    layout['heights'] = {rows[k]: v for k, v in raw.get('heights', {}).items() if k in rows}
    for key, value in raw.get('cells', {}).items():
        r, c = key.split('|')
        if r in rows and c in cols:
            layout['cells'][rows[r] + '|' + cols[c]] = value
    for m in raw.get('merges', []):
        if all(str(r) in rows for r in m['rows']) and all(str(c) in cols for c in m['cols']):
            # Only preserve rectangular areas whose retained rows/columns remain adjacent.
            layout['merges'].append({'rows': [rows[str(r)] for r in m['rows']], 'cols': [cols[str(c)] for c in m['cols']]})
    from .work_lists import _fields
    visible = [str(f['id']) for f in _fields(conn, list_id) if not f['hidden']]
    ordered_rows = [str(r['id']) for r in conn.execute('SELECT id FROM work_list_records WHERE list_id=? ORDER BY id', (list_id,))]
    put_layout(conn, list_id, clean_layout(layout, ordered_rows, visible))


def export_grid(conn, item, fields, rows):
    layout = get_layout(conn, item['id'])
    if not layout:
        return None
    output = io.BytesIO()
    with xlsxwriter.Workbook(output, {'in_memory': True, 'strings_to_formulas': False, 'strings_to_urls': False}) as book:
        sheet = book.add_worksheet('清单')
        sheet.freeze_panes(1, 0)
        row_positions = {'h': 0} | {str(r['id']): i for i, r in enumerate(rows, 1)}
        col_positions = {str(f['id']): i for i, f in enumerate(fields)}
        for key, col in col_positions.items():
            sheet.set_column_pixels(col, col, layout.get('widths', {}).get(key, 150))
        for key, row in row_positions.items():
            sheet.set_row_pixels(row, layout.get('heights', {}).get(key, 36 if key == 'h' else 32))
        formats = {}
        def cell_format(row, col):
            style = layout.get('cells', {}).get(row + '|' + col, {})
            props = {'bold': row == 'h', 'bg_color': '#EFF3F8' if row == 'h' else '#FFFFFF', 'valign': 'vcenter'}
            mapping = {'font': 'font_name', 'size': 'font_size', 'color': 'font_color', 'background': 'bg_color',
                       'bold': 'bold', 'italic': 'italic', 'underline': 'underline', 'wrap': 'text_wrap',
                       'align': 'align', 'number_format': 'num_format'}
            for k, v in style.items():
                if k in mapping:
                    props[mapping[k]] = v
                elif k == 'valign':
                    props['valign'] = 'vcenter' if v == 'center' else v
                elif k.startswith('border_'):
                    edge = k.removeprefix('border_')
                    props[edge] = v['style']
                    if v.get('color'):
                        props[edge + '_color'] = v['color']
            encoded = json.dumps(props, sort_keys=True)
            if encoded not in formats:
                formats[encoded] = book.add_format(props)
            return formats[encoded]
        values = {('h', str(f['id'])): f['label'] for f in fields}
        for row in rows:
            for field in fields:
                value = row['values'].get(str(field['id']), '')
                values[(str(row['id']), str(field['id']))] = '、'.join(value) if isinstance(value, list) else str(value)
        covered = set()
        for merge in layout.get('merges', []):
            if any(r not in row_positions for r in merge['rows']) or any(c not in col_positions for c in merge['cols']):
                continue
            ri, ci = [row_positions[r] for r in merge['rows']], [col_positions[c] for c in merge['cols']]
            if ri != list(range(ri[0], ri[-1] + 1)) or ci != list(range(ci[0], ci[-1] + 1)):
                continue
            r, c = merge['rows'][0], merge['cols'][0]
            sheet.merge_range(ri[0], ci[0], ri[-1], ci[-1], values[(r, c)], cell_format(r, c))
            covered |= {(mr, mc) for mr in merge['rows'] for mc in merge['cols']}
        for (r, c), value in values.items():
            if (r, c) in covered:
                continue
            style = layout.get('cells', {}).get(r + '|' + c, {})
            if r != 'h' and style.get('numeric') and re.fullmatch(r'\d{4}-\d{2}-\d{2}(T[\d:]+)?', value) and re.search('[yd]', style.get('number_format', ''), re.I):
                sheet.write_datetime(row_positions[r], col_positions[c], datetime.fromisoformat(value), cell_format(r, c))
            elif r != 'h' and style.get('numeric') and re.fullmatch(r'-?\d+(\.\d+)?', value) and len(value) < 100:
                sheet.write_number(row_positions[r], col_positions[c], float(value), cell_format(r, c))
            else:
                sheet.write_string(row_positions[r], col_positions[c], value, cell_format(r, c))
        extra_columns = []
        if any(r['status'] != 'pending' for r in rows):
            extra_columns.append(('状态', lambda r: '已完成' if r['status'] == 'done' else '待处理'))
        if any(r['customer_name'] for r in rows):
            extra_columns.append(('关联客户', lambda r: r['customer_name'] or ''))
        if any(r['note'] for r in rows):
            extra_columns.append(('备注', lambda r: r['note']))
        for index, (label, getter) in enumerate(extra_columns, len(fields)):
            sheet.set_column_pixels(index, index, 160)
            sheet.write_string(0, index, label)
            for number, record in enumerate(rows, 1):
                sheet.write_string(number, index, getter(record))
        if fields and not any('h' in m['rows'] for m in layout.get('merges', [])):
            sheet.autofilter(0, 0, len(rows), len(fields) + len(extra_columns) - 1)
    return output.getvalue()
