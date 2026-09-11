from __future__ import annotations

import os
import sys
import tempfile
import zipfile
from pathlib import Path

import xlsxwriter
from starlette.routing import Match

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMPDIR = tempfile.TemporaryDirectory(prefix='chen-assistant-v032-import-')
TEST_DIR = Path(_TMPDIR.name)
os.environ['APP_DB_PATH'] = str(TEST_DIR / 'app.db')

from app.db import db, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.v032_customer_import_routes import (  # noqa: E402
    CONTACT_HEADERS,
    GROUP_HEADERS,
    PROMO_HEADERS,
    SERVICE_HEADERS,
    _build_template,
    _commit_payload,
    _validate_workbook,
)


def first_route(path: str, method: str):
    rows = [
        route for route in app.router.routes
        if getattr(route, 'path', '') == path and method in getattr(route, 'methods', set())
    ]
    assert rows, (path, method)
    return rows[0]


def write_fixture(path: Path):
    workbook = xlsxwriter.Workbook(str(path))
    group = workbook.add_worksheet('集团')
    group.write_row(0, 0, GROUP_HEADERS)
    group.write_row(1, 0, ['G001', '测试集团甲', 'g-test-001', '913700001', '重点客户', '是'])
    group.write_row(2, 0, ['G002', '测试集团乙', 'g-test-002', '913700002', '', '否'])

    service = workbook.add_worksheet('业务')
    service.write_row(0, 0, SERVICE_HEADERS)
    service.write_row(1, 0, ['S001', 'G001', '成员', '张三', '15800000001', '53380001', 40, '固定', '每月', '', '微信', '', '', '', ''])
    service.write_row(2, 0, ['S002', 'G001', '宽带', '后勤', '', '53380002', 560, '变动', '每月', '', '转账', '', '', '', ''])
    service.write_row(3, 0, ['S003', 'G002', '专线', '', '', '100001', 1200, '固定', '12个月', '2027-09', '', '', '', '2026-09-01', ''])

    contact = workbook.add_worksheet('联系人')
    contact.write_row(0, 0, CONTACT_HEADERS)
    contact.write_row(1, 0, ['G001', '关键联系人', '王经理', '财务', '13800000000'])

    promo = workbook.add_worksheet('优惠')
    promo.write_row(0, 0, PROMO_HEADERS)
    promo.write_row(1, 0, ['S001', '测试优惠', '2026-01-01', '2026-12-31', 60, ''])
    workbook.close()


def test_routes_and_version():
    # Application shell is v1.0; the customer import/exchange file format remains v0.3.2.
    assert app.version == '1.0'
    new_get = first_route('/customers/new', 'GET')
    assert new_get.endpoint.__module__ == 'app.v032_customer_import_routes'
    assert first_route('/customers/new', 'POST').endpoint.__module__ == 'app.v032_customer_import_routes'
    # The original multi-table routes remain registered only as a compatibility
    # layer. The visible customer UI continues to use the one-customer-per-sheet exchange.
    assert first_route('/customers/import-template-v032.xlsx', 'GET').endpoint.__module__ == 'app.v032_customer_import_routes'
    assert first_route('/customers/import-v032/preview', 'POST').endpoint.__module__ == 'app.v032_customer_import_routes'
    assert first_route('/customers/import-v032/confirm', 'POST').endpoint.__module__ == 'app.v032_customer_import_routes'

    # /customers/new must never be swallowed by /customers/{customer_id}.
    detail = first_route('/customers/{customer_id}', 'GET')
    new_scope = {'type': 'http', 'path': '/customers/new', 'method': 'GET'}
    id_scope = {'type': 'http', 'path': '/customers/123', 'method': 'GET'}
    assert detail.matches(new_scope)[0] == Match.NONE
    assert detail.matches(id_scope)[0] == Match.FULL
    full_matches = [
        route for route in app.router.routes
        if hasattr(route, 'matches') and route.matches(new_scope)[0] == Match.FULL
    ]
    assert full_matches
    assert full_matches[0] is new_get
    assert full_matches[0].endpoint.__module__ == 'app.v032_customer_import_routes'


def test_template_contract():
    init_db()
    data = _build_template()
    assert data[:2] == b'PK'
    path = TEST_DIR / 'template.xlsx'
    path.write_bytes(data)
    with zipfile.ZipFile(path) as archive:
        assert 'xl/workbook.xml' in archive.namelist()
        workbook_xml = archive.read('xl/workbook.xml').decode('utf-8')
        for name in ('填写说明', '集团', '业务', '联系人', '优惠', '_字典'):
            assert name in workbook_xml, name
        assert 'definedNames' in workbook_xml


def test_validation_commit_and_fixed_confirmation():
    init_db()
    fixture = TEST_DIR / 'fixture.xlsx'
    write_fixture(fixture)
    preview = _validate_workbook(fixture, fixture.name)
    assert preview['errors'] == [], preview['errors']
    assert preview['summary'] == {'groups': 2, 'services': 3, 'contacts': 1, 'promotions': 1}
    result = _commit_payload(preview)
    assert result['customers'] == 2 and result['services'] == 3

    with db() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM customers').fetchone()['n'] == 2
        assert conn.execute('SELECT COUNT(*) n FROM services').fetchone()['n'] == 3
        fixed = conn.execute(
            '''SELECT pe.confirmed,pe.source,r.mode,r.fixed_amount
               FROM services s JOIN payment_entries pe ON pe.service_id=s.id
               JOIN service_payment_rules r ON r.service_id=s.id
               WHERE s.number='15800000001' LIMIT 1'''
        ).fetchone()
        assert fixed['mode'] == 'fixed'
        assert fixed['confirmed'] == 1
        assert fixed['source'] == 'fixed'
        assert float(fixed['fixed_amount']) == 40
        variable = conn.execute(
            '''SELECT pe.confirmed,r.mode FROM services s
               JOIN payment_entries pe ON pe.service_id=s.id
               JOIN service_payment_rules r ON r.service_id=s.id
               WHERE s.account='53380002' LIMIT 1'''
        ).fetchone()
        assert variable['mode'] == 'variable'
        assert variable['confirmed'] == 0
        customer = conn.execute("SELECT payment_enabled FROM customers WHERE group_code='g-test-002'").fetchone()
        assert customer['payment_enabled'] == 0

    duplicate_preview = _validate_workbook(fixture, fixture.name)
    assert duplicate_preview['errors']
    assert any('已存在' in item['message'] for item in duplicate_preview['errors'])


def test_confirm_is_atomic_when_duplicate_appears():
    with db() as conn:
        before = conn.execute('SELECT COUNT(*) n FROM customers').fetchone()['n']
    payload = {
        'groups': [
            {'import_id': 'G100', 'name': '测试集团甲', 'group_code': 'new-code', 'tax_id': '', 'relation_summary': '', 'payment_enabled': True, 'source_row': 2},
            {'import_id': 'G101', 'name': '全新集团', 'group_code': 'brand-new', 'tax_id': '', 'relation_summary': '', 'payment_enabled': True, 'source_row': 3},
        ],
        'services': [], 'contacts': [], 'promotions': [], 'errors': [], 'warnings': [],
    }
    try:
        _commit_payload(payload)
        raise AssertionError('duplicate batch should have been rejected')
    except ValueError:
        pass
    with db() as conn:
        after = conn.execute('SELECT COUNT(*) n FROM customers').fetchone()['n']
        assert after == before
        assert conn.execute("SELECT COUNT(*) n FROM customers WHERE group_code='brand-new'").fetchone()['n'] == 0


def test_ui_contract():
    template = (ROOT / 'app/templates/customer_form.html').read_text(encoding='utf-8')
    css = (ROOT / 'app/static/v032_customer_import.css').read_text(encoding='utf-8')
    base = (ROOT / 'app/templates/base.html').read_text(encoding='utf-8')
    assert '单个新建' in template and 'Excel批量导入/导出' in template
    assert '下载最新 Excel 模板' in template
    assert '上传并检查' in template and '确认导入全部客户' in template
    assert '导出全部客户 Excel' in template
    assert '/customers/import-template-v032-one-sheet.xlsx' in template
    assert '/customers/import-v032-one-sheet/preview' in template
    assert '/customers/import-v032-one-sheet/confirm' in template
    assert '/customers/export-v032.xlsx' in template
    assert 'v032-preview-metrics' in css
    assert '/static/v032_customer_import.css' in base
    assert 'v1.0' in base


if __name__ == '__main__':
    test_routes_and_version()
    test_template_contract()
    test_validation_commit_and_fixed_confirmation()
    test_confirm_is_atomic_when_duplicate_appears()
    test_ui_contract()
    print('v1.0 app + v0.3.2 customer creation/import compatibility contract passed (isolated database)')
