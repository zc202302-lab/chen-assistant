import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from .config import DB_PATH, DATA_DIR

SCHEMA = r'''
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_sheet TEXT UNIQUE,
    name TEXT NOT NULL,
    group_code TEXT DEFAULT '',
    tax_id TEXT DEFAULT '',
    relation_summary TEXT DEFAULT '',
    payment_enabled INTEGER NOT NULL DEFAULT 0,
    notified INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    payment_period TEXT DEFAULT '',
    employee_own TEXT DEFAULT '',
    employee_share TEXT DEFAULT '',
    leased_own TEXT DEFAULT '',
    leased_other TEXT DEFAULT '',
    other_status TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customer_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    group_code TEXT DEFAULT '',
    tax_id TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    kind TEXT DEFAULT '',
    name TEXT DEFAULT '',
    relationship TEXT DEFAULT '',
    phone TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS invoice_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    service_type TEXT DEFAULT '',
    holder_name TEXT DEFAULT '',
    number TEXT DEFAULT '',
    account TEXT DEFAULT '',
    monthly_fee REAL DEFAULT 0,
    fixed_fee INTEGER DEFAULT 0,
    payment_cycle TEXT DEFAULT '',
    payment_method TEXT DEFAULT '',
    invoice_type TEXT DEFAULT '',
    package_type TEXT DEFAULT '',
    last_payment_date TEXT DEFAULT '',
    invoice_group_id INTEGER DEFAULT NULL,
    active_from_period TEXT DEFAULT '',
    inactive_from_period TEXT DEFAULT '',
    source_row INTEGER DEFAULT 0,
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS service_payment_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    effective_period TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('fixed','variable')),
    fixed_amount REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(service_id, effective_period)
);

CREATE TABLE IF NOT EXISTS payment_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    period TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    reference_amount REAL DEFAULT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    confirmed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(service_id, period)
);

CREATE TABLE IF NOT EXISTS promotions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    name TEXT DEFAULT '',
    expiry_date TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    remind_date TEXT DEFAULT '',
    note TEXT DEFAULT '',
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    visit_date TEXT DEFAULT '',
    kind TEXT DEFAULT '拜访',
    result TEXT DEFAULT '',
    plan TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS website_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    url TEXT DEFAULT '',
    username TEXT DEFAULT '',
    email TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    password_enc TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    csrf_token TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name);
CREATE INDEX IF NOT EXISTS idx_services_customer ON services(customer_id);
CREATE INDEX IF NOT EXISTS idx_services_type ON services(service_type);
CREATE INDEX IF NOT EXISTS idx_services_number ON services(number);
CREATE INDEX IF NOT EXISTS idx_payment_entries_period ON payment_entries(period, service_id);
CREATE INDEX IF NOT EXISTS idx_invoice_groups_customer ON invoice_groups(customer_id);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(done, remind_date);
CREATE INDEX IF NOT EXISTS idx_promotions_expiry ON promotions(expiry_date);
'''


def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row['name'] == column for row in conn.execute(f'PRAGMA table_info({table})').fetchall())


def _migrate(conn: sqlite3.Connection):
    # v0.1 -> v0.1.1。注意：依赖新增列的索引必须在 ALTER TABLE 之后创建。
    if not _has_column(conn, 'services', 'invoice_group_id'):
        conn.execute('ALTER TABLE services ADD COLUMN invoice_group_id INTEGER DEFAULT NULL')

    # v0.2：业务按月份启用/停用，停止使用不删除历史。
    if not _has_column(conn, 'services', 'active_from_period'):
        conn.execute("ALTER TABLE services ADD COLUMN active_from_period TEXT DEFAULT ''")
    if not _has_column(conn, 'services', 'inactive_from_period'):
        conn.execute("ALTER TABLE services ADD COLUMN inactive_from_period TEXT DEFAULT ''")

    # v0.1.1 的 payment_entries 没有这两列，补齐后保留已有数据。
    if not _has_column(conn, 'payment_entries', 'confirmed'):
        conn.execute('ALTER TABLE payment_entries ADD COLUMN confirmed INTEGER NOT NULL DEFAULT 0')
        conn.execute("UPDATE payment_entries SET confirmed=1 WHERE source IN ('manual','fixed')")
    if not _has_column(conn, 'payment_entries', 'reference_amount'):
        conn.execute('ALTER TABLE payment_entries ADD COLUMN reference_amount REAL DEFAULT NULL')
        conn.execute('UPDATE payment_entries SET reference_amount=amount WHERE reference_amount IS NULL')

    # 从 v0.1 直接升级时，把原 monthly_fee 作为当前月参考值；变动金额仍需本月重新核对。
    marker = conn.execute("SELECT value FROM app_meta WHERE key='payment_history_bootstrap_v1'").fetchone()
    if not marker:
        period = datetime.now().strftime('%Y-%m')
        now = now_iso()
        conn.execute(
            '''INSERT OR IGNORE INTO payment_entries(service_id,period,amount,reference_amount,source,confirmed,created_at,updated_at)
               SELECT id, ?, COALESCE(monthly_fee,0), COALESCE(monthly_fee,0), 'imported',
                      CASE WHEN fixed_fee=1 THEN 1 ELSE 0 END, ?, ?
               FROM services''',
            (period, now, now),
        )
        conn.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('payment_history_bootstrap_v1',?)", (period,))

    # 为已有业务建立基线规则。之后每次固定/变动切换都新增当前月份规则，不改历史。
    now = now_iso()
    conn.execute(
        '''INSERT OR IGNORE INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
           SELECT id,'1900-01',CASE WHEN fixed_fee=1 THEN 'fixed' ELSE 'variable' END,
                  CASE WHEN fixed_fee=1 THEN COALESCE(monthly_fee,0) ELSE 0 END,?
           FROM services''',
        (now,),
    )

    conn.execute('CREATE INDEX IF NOT EXISTS idx_services_invoice_group ON services(invoice_group_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_payment_rules_service_period ON service_payment_rules(service_id,effective_period)')


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')
