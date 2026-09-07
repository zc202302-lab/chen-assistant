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
    source_row INTEGER DEFAULT 0,
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS payment_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    period TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
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
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
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
    # v0.1 -> v0.1.1：老数据库没有开票分组字段。
    if not _has_column(conn, 'services', 'invoice_group_id'):
        conn.execute('ALTER TABLE services ADD COLUMN invoice_group_id INTEGER DEFAULT NULL')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_services_invoice_group ON services(invoice_group_id)')

    # 第一次升级时，把 Excel / v0.1 中 I 列的当前金额保存为本月缴费金额，避免升级后丢失现状。
    marker = conn.execute("SELECT value FROM app_meta WHERE key='payment_history_bootstrap_v1'").fetchone()
    if not marker:
        period = datetime.now().strftime('%Y-%m')
        now = now_iso()
        conn.execute('''INSERT OR IGNORE INTO payment_entries(service_id,period,amount,source,created_at,updated_at)
                        SELECT id, ?, monthly_fee, 'imported', ?, ? FROM services
                        WHERE COALESCE(monthly_fee,0) <> 0''', (period, now, now))
        conn.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('payment_history_bootstrap_v1',?)", (period,))


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
