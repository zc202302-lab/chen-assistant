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
    payment_display_attr_1 TEXT DEFAULT 'service_type',
    payment_display_attr_2 TEXT DEFAULT 'holder_name',
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
    payment_interval_months INTEGER DEFAULT 0,
    next_payment_period TEXT DEFAULT '',
    payment_method TEXT DEFAULT '',
    invoice_type TEXT DEFAULT '',
    package_type TEXT DEFAULT '',
    last_payment_date TEXT DEFAULT '',
    invoice_group_id INTEGER DEFAULT NULL,
    active_from_period TEXT DEFAULT '',
    inactive_from_period TEXT DEFAULT '',
    source_row INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    display_attr_1 TEXT DEFAULT 'service_type',
    display_attr_2 TEXT DEFAULT 'holder_name',
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

CREATE TABLE IF NOT EXISTS customer_payment_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    period TEXT NOT NULL,
    notified_at TEXT DEFAULT '',
    paid_at TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(customer_id, period)
);

CREATE TABLE IF NOT EXISTS promotions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    name TEXT DEFAULT '',
    start_date TEXT DEFAULT '',
    expiry_date TEXT DEFAULT '',
    remind_days INTEGER NOT NULL DEFAULT 60,
    status TEXT NOT NULL DEFAULT 'active',
    renewed_at TEXT DEFAULT '',
    renewed_to_id INTEGER DEFAULT NULL,
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    remind_date TEXT DEFAULT '',
    remind_at TEXT DEFAULT '',
    note TEXT DEFAULT '',
    is_payment_review INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT DEFAULT ''
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
CREATE INDEX IF NOT EXISTS idx_payment_runs_customer_period ON customer_payment_runs(customer_id, period);
CREATE INDEX IF NOT EXISTS idx_invoice_groups_customer ON invoice_groups(customer_id);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(done, remind_date);
CREATE INDEX IF NOT EXISTS idx_promotions_expiry ON promotions(expiry_date);
'''


def connect():
    """Open one short-lived SQLite connection with production-safe lock handling.

    WAL allows readers and a writer to coexist, but bursts of browser requests can
    still briefly contend for the single SQLite write lock.  A generous timeout
    turns those normal short races into waiting instead of intermittent
    ``database is locked`` failures.  ``synchronous=NORMAL`` is the SQLite-recommended
    WAL durability/performance balance; foreign keys remain enforced per connection.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=30000')
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


@contextmanager
def db(immediate=False):
    conn = connect()
    try:
        if immediate:
            conn.execute('BEGIN IMMEDIATE')
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def connection_scope(conn=None):
    """Borrow an existing transaction, or own a connection with real rollback."""
    if conn is None:
        with db() as owned:
            owned.execute('BEGIN')
            yield owned
    else:
        yield conn


def execute_schema(conn, script):
    """Execute complete SQL statements without executescript's implicit commit."""
    if not conn.in_transaction:
        conn.execute('BEGIN')
    statement = ''
    for char in script:
        statement += char
        if char == ';' and sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ''
    if statement.strip():
        conn.execute(statement)


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row['name'] == column for row in conn.execute(f'PRAGMA table_info({table})').fetchall())


def _cycle_months(text: str) -> int:
    s = (text or '').strip()
    if s in {'月', '每月', '1个月'}:
        return 1
    if s in {'季度', '季', '3个月'}:
        return 3
    if s in {'半年', '6个月'}:
        return 6
    if s in {'年', '每年', '12个月'}:
        return 12
    if s.endswith('个月'):
        try:
            n = int(s[:-2])
            return n if n > 0 else 0
        except Exception:
            return 0
    return 0


def _period_add(period: str, months: int) -> str:
    try:
        y, m = [int(x) for x in period[:7].split('-')]
    except Exception:
        return ''
    idx = y * 12 + (m - 1) + months
    return f'{idx // 12:04d}-{idx % 12 + 1:02d}'


def _migrate(conn: sqlite3.Connection):
    if not _has_column(conn, 'services', 'invoice_group_id'):
        conn.execute('ALTER TABLE services ADD COLUMN invoice_group_id INTEGER DEFAULT NULL')
    if not _has_column(conn, 'services', 'active_from_period'):
        conn.execute("ALTER TABLE services ADD COLUMN active_from_period TEXT DEFAULT ''")
    if not _has_column(conn, 'services', 'inactive_from_period'):
        conn.execute("ALTER TABLE services ADD COLUMN inactive_from_period TEXT DEFAULT ''")

    # v1.6.4: richer customer tasks. Existing date-only reminders remain valid and
    # are copied into remind_at without inventing a time.
    if not _has_column(conn, 'tasks', 'remind_at'):
        conn.execute("ALTER TABLE tasks ADD COLUMN remind_at TEXT DEFAULT ''")
        conn.execute("UPDATE tasks SET remind_at=remind_date WHERE COALESCE(remind_at,'')='' AND COALESCE(remind_date,'')<>''")
    if not _has_column(conn, 'tasks', 'is_payment_review'):
        conn.execute('ALTER TABLE tasks ADD COLUMN is_payment_review INTEGER NOT NULL DEFAULT 0')
    if not _has_column(conn, 'tasks', 'updated_at'):
        conn.execute("ALTER TABLE tasks ADD COLUMN updated_at TEXT DEFAULT ''")
        conn.execute("UPDATE tasks SET updated_at=created_at WHERE COALESCE(updated_at,'')=''")

    if not _has_column(conn, 'payment_entries', 'confirmed'):
        conn.execute('ALTER TABLE payment_entries ADD COLUMN confirmed INTEGER NOT NULL DEFAULT 0')
        conn.execute("UPDATE payment_entries SET confirmed=1 WHERE source IN ('manual','fixed')")
    if not _has_column(conn, 'payment_entries', 'reference_amount'):
        conn.execute('ALTER TABLE payment_entries ADD COLUMN reference_amount REAL DEFAULT NULL')
        conn.execute('UPDATE payment_entries SET reference_amount=amount WHERE reference_amount IS NULL')

    added_sort = False
    if not _has_column(conn, 'services', 'sort_order'):
        conn.execute('ALTER TABLE services ADD COLUMN sort_order INTEGER DEFAULT 0')
        added_sort = True
    if not _has_column(conn, 'services', 'display_attr_1'):
        conn.execute("ALTER TABLE services ADD COLUMN display_attr_1 TEXT DEFAULT 'service_type'")
    if not _has_column(conn, 'services', 'display_attr_2'):
        conn.execute("ALTER TABLE services ADD COLUMN display_attr_2 TEXT DEFAULT 'holder_name'")
    if added_sort:
        conn.execute('''UPDATE services
                        SET sort_order = CASE WHEN COALESCE(source_row,0)>0 THEN source_row*10 ELSE id*10 END''')
    conn.execute("UPDATE services SET display_attr_1='service_type' WHERE COALESCE(display_attr_1,'')='' ")
    conn.execute("UPDATE services SET display_attr_2='holder_name' WHERE COALESCE(display_attr_2,'')='' ")

    if not _has_column(conn, 'customers', 'payment_display_attr_1'):
        conn.execute("ALTER TABLE customers ADD COLUMN payment_display_attr_1 TEXT DEFAULT 'service_type'")
    if not _has_column(conn, 'customers', 'payment_display_attr_2'):
        conn.execute("ALTER TABLE customers ADD COLUMN payment_display_attr_2 TEXT DEFAULT 'holder_name'")
    conn.execute("UPDATE customers SET payment_display_attr_1='service_type' WHERE COALESCE(payment_display_attr_1,'')='' ")
    conn.execute("UPDATE customers SET payment_display_attr_2='holder_name' WHERE COALESCE(payment_display_attr_2,'')='' ")

    # v0.2.5: explicit payment schedule. Existing free-text cycle is preserved and used to bootstrap it.
    if not _has_column(conn, 'services', 'payment_interval_months'):
        conn.execute('ALTER TABLE services ADD COLUMN payment_interval_months INTEGER DEFAULT 0')
    if not _has_column(conn, 'services', 'next_payment_period'):
        conn.execute("ALTER TABLE services ADD COLUMN next_payment_period TEXT DEFAULT ''")
    current_period = datetime.now().strftime('%Y-%m')
    rows = conn.execute('SELECT id,payment_cycle,last_payment_date,payment_interval_months,next_payment_period FROM services').fetchall()
    for row in rows:
        interval = int(row['payment_interval_months'] or 0)
        if interval <= 0:
            interval = _cycle_months(row['payment_cycle'])
        next_period = (row['next_payment_period'] or '').strip()
        if interval > 1 and not next_period:
            last = (row['last_payment_date'] or '').strip()
            next_period = _period_add(last[:7], interval) if len(last) >= 7 else current_period
        conn.execute('UPDATE services SET payment_interval_months=?,next_payment_period=? WHERE id=?',
                     (interval, next_period, row['id']))

    # v0.2.5: promotion lifecycle fields; old imported rows remain active.
    if not _has_column(conn, 'promotions', 'start_date'):
        conn.execute("ALTER TABLE promotions ADD COLUMN start_date TEXT DEFAULT ''")
    if not _has_column(conn, 'promotions', 'remind_days'):
        conn.execute('ALTER TABLE promotions ADD COLUMN remind_days INTEGER NOT NULL DEFAULT 60')
    if not _has_column(conn, 'promotions', 'status'):
        conn.execute("ALTER TABLE promotions ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    if not _has_column(conn, 'promotions', 'renewed_at'):
        conn.execute("ALTER TABLE promotions ADD COLUMN renewed_at TEXT DEFAULT ''")
    if not _has_column(conn, 'promotions', 'renewed_to_id'):
        conn.execute('ALTER TABLE promotions ADD COLUMN renewed_to_id INTEGER DEFAULT NULL')
    if not _has_column(conn, 'promotions', 'notes'):
        conn.execute("ALTER TABLE promotions ADD COLUMN notes TEXT DEFAULT ''")
    if not _has_column(conn, 'promotions', 'created_at'):
        conn.execute("ALTER TABLE promotions ADD COLUMN created_at TEXT DEFAULT ''")
    conn.execute("UPDATE promotions SET status='active' WHERE COALESCE(status,'')='' ")
    conn.execute('UPDATE promotions SET remind_days=60 WHERE remind_days IS NULL OR remind_days<0')
    conn.execute('UPDATE promotions SET created_at=? WHERE COALESCE(created_at,\'\')=\'\'', (now_iso(),))

    marker = conn.execute("SELECT value FROM app_meta WHERE key='payment_history_bootstrap_v1'").fetchone()
    if not marker:
        period = current_period
        now = now_iso()
        conn.execute(
            '''INSERT OR IGNORE INTO payment_entries(service_id,period,amount,reference_amount,source,confirmed,created_at,updated_at)
               SELECT id, ?, COALESCE(monthly_fee,0), COALESCE(monthly_fee,0), 'imported',
                      CASE WHEN fixed_fee=1 THEN 1 ELSE 0 END, ?, ?
               FROM services''',
            (period, now, now),
        )
        conn.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('payment_history_bootstrap_v1',?)", (period,))

    now = now_iso()
    conn.execute(
        '''INSERT OR IGNORE INTO service_payment_rules(service_id,effective_period,mode,fixed_amount,created_at)
           SELECT id,'1900-01',CASE WHEN fixed_fee=1 THEN 'fixed' ELSE 'variable' END,
                  CASE WHEN fixed_fee=1 THEN COALESCE(monthly_fee,0) ELSE 0 END,?
           FROM services''',
        (now,),
    )

    # Carry the legacy customer-level notified/completed flags into the new monthly run table once.
    legacy_rows = conn.execute(
        "SELECT id,payment_period,notified,completed,created_at,updated_at FROM customers WHERE COALESCE(payment_period,'')<>''"
    ).fetchall()
    for c in legacy_rows:
        notified_at = c['updated_at'] if c['notified'] else ''
        paid_at = c['updated_at'] if c['completed'] else ''
        conn.execute(
            '''INSERT OR IGNORE INTO customer_payment_runs
               (customer_id,period,notified_at,paid_at,created_at,updated_at)
               VALUES(?,?,?,?,?,?)''',
            (c['id'], c['payment_period'], notified_at, paid_at, c['created_at'] or now, c['updated_at'] or now),
        )

    conn.execute('CREATE INDEX IF NOT EXISTS idx_services_invoice_group ON services(invoice_group_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_services_customer_sort ON services(customer_id,sort_order,id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_payment_rules_service_period ON service_payment_rules(service_id,effective_period)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_payment_runs_customer_period ON customer_payment_runs(customer_id,period)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_promotions_service_status ON promotions(service_id,status,expiry_date)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_customer_review ON tasks(customer_id,is_payment_review,done)')


def init_db():
    with db() as conn:
        execute_schema(conn, SCHEMA)
        _migrate(conn)
        from .payment_schedule import ensure_payment_date_schema
        ensure_payment_date_schema(conn)
        from .promotions import ensure_promotion_schema
        ensure_promotion_schema(conn)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')
