from __future__ import annotations

import json
import os
import sys
import tempfile
from io import BytesIO
from pathlib import Path

import xlsxwriter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v032-exchange-')
os.environ['APP_DB_PATH'] = str(Path(_TMPDIR.name) / 'app.db')

from app.db import db, init_db  # noqa: E402
from app.importer import XlsmReader  # noqa: E402
from app.main import app  # noqa: E402
from app.v027_routes import _meta_set  # noqa: E402
from app.v028_routes import DEFAULT_TEMPLATE, TEMPLATE_META_KEY, _template  # noqa: E402
from app.v032_customer_exchange_routes import (  # noqa: E402
    FORMAT_MARKER,
    _build_blank_template,
    _build_export,
    _commit,
    _validate_workbook,
    _write_customer_sheet,
)


def first_route(path: str, method: str):
    rows = [r for r in app.router.routes if getattr(r, 'path', '') == path and method in getattr(r, 'methods', set())]
    assert rows, (path, method)
    return rows[0]


def install_dynamic_template():
    template = [dict(x) for x in DEFAULT_TEMPLATE]
    template.append({'key': 'custom_123456abcdef', 'label': '后勤分类', 'kind': 'text', 'core': False})
    with db() as conn:
        _meta_set(conn, TEMPLATE_META_KEY, json.dumps(template, ensure_ascii=False))
    return template


def customer_payload(name: str, code: str, number: str, attr_value: str):
    return {
        'info': {
            'name': name, 'group_code': code, 'tax_id': '', 'relation_summary': '测试客情', 'payment_enabled': '是',
            'payment_display_attr_1': '类型', 'payment_display_attr_2': '姓名/属性',
            'mail_subject': f'{name}缴费', 'mail_body': '请处理', 'attachment_filename': f'{name}.txt',
            'employee_own': '', 'employee_share': '', 'leased_own': '', 'leased_other': '', 'other_status': '',
        },
        'entities': [],
        'invoices': [['默认开票组', '']],
        'businesses': [[
            'S001', '成员', '张三', number, '53380001', 1, '微信', '', '默认开票组', '', '', '', '', attr_value,
            40, '固定', '', '启用', '', '', '', 10,
        ]],
        'contacts': [['关键联系人', '王经理', '财务', '13800000000']],
        'promotions': [['S001', '测试优惠', '2026-01-01', '2026-12-31', 60, 'active', '']],
        'tasks': [['测试待办', '2026-09-30', '', '否']],
        'visits': [['2026-09-01', '拜访', '正常', '继续跟进']],
        'rules': [], 'payments': [], 'runs': [],
    }


def write_fixture(path: Path, template):
    workbook = xlsxwriter.Workbook(str(path))
    _write_customer_sheet(workbook, workbook.add_worksheet('客户甲'), template, customer_payload('测试客户甲', 'g-ex-001', '15800000001', '后勤A'))
    _write_customer_sheet(workbook, workbook.add_worksheet('客户乙'), template, customer_payload('测试客户乙', 'g-ex-002', '15800000002', '后勤B'))
    workbook.close()


def test_route_contract():
    assert first_route('/customers/import-template-v032-one-sheet.xlsx', 'GET').endpoint.__module__ == 'app.v032_customer_exchange_routes'
    assert first_route('/customers/export-v032.xlsx', 'GET').endpoint.__module__ == 'app.v032_customer_exchange_routes'
    assert first_route('/customers/import-v032-one-sheet/preview', 'POST').endpoint.__module__ == 'app.v032_customer_exchange_routes'
    assert first_route('/customers/import-v032-one-sheet/confirm', 'POST').endpoint.__module__ == 'app.v032_customer_exchange_routes'


def test_dynamic_template_import_export_roundtrip():
    init_db()
    template = install_dynamic_template()

    blank = Path(_TMPDIR.name) / 'blank.xlsx'
    blank.write_bytes(_build_blank_template())
    reader = XlsmReader(blank)
    assert len(reader.sheets) == 1
    assert reader.sheets[0][0] == '客户1'
    cells = reader.cells(reader.sheets[0][1])
    assert cells.get('A1') == FORMAT_MARKER
    assert '后勤分类' in cells.values()
    assert 'attr:custom_123456abcdef' in cells.values()

    fixture = Path(_TMPDIR.name) / 'two-customers.xlsx'
    write_fixture(fixture, template)
    preview = _validate_workbook(fixture, fixture.name)
    assert preview['errors'] == [], preview['errors']
    assert preview['summary'] == {'groups': 2, 'services': 2, 'contacts': 2, 'promotions': 2}
    result = _commit(preview)
    assert result['customers'] == 2 and result['services'] == 2

    with db() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM customers').fetchone()['n'] == 2
        custom = conn.execute("SELECT value FROM service_custom_attributes WHERE attr_key='custom_123456abcdef' ORDER BY service_id").fetchall()
        assert [r['value'] for r in custom] == ['后勤A', '后勤B']
        fixed = conn.execute('SELECT confirmed,source FROM payment_entries ORDER BY service_id').fetchall()
        assert all(r['confirmed'] == 1 and r['source'] == 'fixed' for r in fixed)
        assert len(_template(conn)) == len(template)

    exported = Path(_TMPDIR.name) / 'export.xlsx'
    exported.write_bytes(_build_export())
    exported_reader = XlsmReader(exported)
    assert len(exported_reader.sheets) == 2
    names = {name for name, _ in exported_reader.sheets}
    assert names == {'测试客户甲', '测试客户乙'}
    exported_values = []
    for _, sheet_path in exported_reader.sheets:
        values = exported_reader.cells(sheet_path).values()
        exported_values.extend(values)
    assert '后勤分类' in exported_values
    assert '后勤A' in exported_values and '后勤B' in exported_values
    assert '测试待办' in exported_values and '继续跟进' in exported_values


def test_template_changes_after_attribute_change():
    init_db()
    install_dynamic_template()
    first = Path(_TMPDIR.name) / 'first.xlsx'
    first.write_bytes(_build_blank_template())
    with db() as conn:
        template = _template(conn)
        template[-1]['label'] = '后勤归类'
        _meta_set(conn, TEMPLATE_META_KEY, json.dumps(template, ensure_ascii=False))
    second = Path(_TMPDIR.name) / 'second.xlsx'
    second.write_bytes(_build_blank_template())
    values = XlsmReader(second).cells(XlsmReader(second).sheets[0][1]).values()
    assert '后勤归类' in values
    assert '后勤分类' not in values


if __name__ == '__main__':
    test_route_contract()
    test_dynamic_template_import_export_roundtrip()
    test_template_changes_after_attribute_change()
    print('v0.3.2 one-customer-per-sheet dynamic import/export contract passed')
