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

from app import config  # noqa: E402
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
    # The application shell may evolve independently; the customer import/exchange
    # file format and mature v0.3.2 work routes remain unchanged.
    assert app.version == config.APP_VERSION
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
    payload = _build_template()
    fixture = Path(_TMPDIR.name) / 'template.xlsx'
    fixture.write_bytes(payload)
    assert zipfile.is_zipfile(fixture)


def test_import_contract():
    init_db()
    fixture = Path(_TMPDIR.name) / 'fixture.xlsx'
    write_fixture(fixture)
    preview = _validate_workbook(fixture, fixture.name)
    assert preview['errors'] == [], preview['errors']
    assert preview['summary'] == {'groups': 2, 'services': 3, 'contacts': 1, 'promotions': 1}
    result = _commit_payload(preview)
    assert result['customers'] == 2
    assert result['services'] == 3
    with db() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM customers').fetchone()['n'] == 2
        assert conn.execute('SELECT COUNT(*) n FROM services').fetchone()['n'] == 3
        fixed = conn.execute("SELECT confirmed,source FROM payment_entries WHERE service_id IN (SELECT id FROM services WHERE fixed_amount=1)").fetchall()
        assert fixed and all(row['confirmed'] == 1 and row['source'] == 'fixed' for row in fixed)


if __name__ == '__main__':
    test_routes_and_version()
    test_template_contract()
    test_import_contract()
    print('v0.3.2 customer import contract passed under current app shell')
