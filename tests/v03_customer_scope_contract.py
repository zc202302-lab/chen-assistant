from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import db, init_db, now_iso  # noqa: E402
from app.v027_routes import _meta_set  # noqa: E402
from app.v028_routes import _template, TEMPLATE_META_KEY  # noqa: E402
from app.v0212_business_display_routes import (  # noqa: E402
    SYSTEM_PAYMENT_STATE_KEY,
    _customer_display_key,
    _ordered_keys,
)

DB = ROOT / 'data' / 'app.db'
for suffix in ('', '-wal', '-shm'):
    p = Path(str(DB) + suffix)
    if p.exists():
        p.unlink()


def main():
    init_db()
    now = now_iso()
    with db() as conn:
        c1 = int(conn.execute(
            'INSERT INTO customers(name,group_code,tax_id,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            ('客户A', 'A001', '', 1, now, now),
        ).lastrowid)
        c2 = int(conn.execute(
            'INSERT INTO customers(name,group_code,tax_id,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            ('客户B', 'B001', '', 1, now, now),
        ).lastrowid)

        # Attribute definition/template is global: both customers read the same template.
        template = _template(conn)
        custom = {'key': 'custom_123456789abc', 'label': '全局测试属性', 'kind': 'text', 'core': False}
        global_template = [*template, custom]
        _meta_set(conn, TEMPLATE_META_KEY, json.dumps(global_template, ensure_ascii=False))
        assert any(x['key'] == custom['key'] for x in _template(conn))

        # Display order is isolated per customer.
        _meta_set(
            conn,
            _customer_display_key(c1),
            json.dumps(['number', 'account', custom['key']], ensure_ascii=False),
        )
        _meta_set(
            conn,
            _customer_display_key(c2),
            json.dumps([SYSTEM_PAYMENT_STATE_KEY, 'holder_name'], ensure_ascii=False),
        )
        a = _ordered_keys(conn, global_template, c1)
        b = _ordered_keys(conn, global_template, c2)
        assert a == ['number', 'account', custom['key']], a
        assert b == [SYSTEM_PAYMENT_STATE_KEY, 'holder_name'], b

        # Changing A's display must not mutate B's display.
        _meta_set(conn, _customer_display_key(c1), json.dumps(['account'], ensure_ascii=False))
        assert _ordered_keys(conn, global_template, c1) == ['account']
        assert _ordered_keys(conn, global_template, c2) == b

        # Removing a template attribute is global and invalid display keys are cleaned
        # independently for every customer the next time its display config is read.
        reduced_template = [x for x in global_template if x['key'] != custom['key']]
        _meta_set(conn, TEMPLATE_META_KEY, json.dumps(reduced_template, ensure_ascii=False))
        assert all(x['key'] != custom['key'] for x in _template(conn))
        assert custom['key'] not in _ordered_keys(conn, reduced_template, c1)
        assert custom['key'] not in _ordered_keys(conn, reduced_template, c2)

    print('v0.3 customer scope contract passed')


if __name__ == '__main__':
    main()
