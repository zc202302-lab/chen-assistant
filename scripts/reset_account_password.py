"""Interactive server-only recovery; preserve encryption keys and all business data."""
import getpass
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config
from app.account_security import check_new_password, ensure_account_schema, replace_password
from app.db import db


def main():
    if not config.DB_PATH.is_file() or not config.APP_ENCRYPTION_KEY or not config.APP_SESSION_SECRET:
        raise SystemExit('未找到现有数据库或安全配置，未作修改。请在现有服务器项目目录运行。')
    password = getpass.getpass('输入新登录密码：')
    confirmation = getpass.getpass('再次输入：')
    try:
        check_new_password(password, confirmation)
    except ValueError as exc:
        raise SystemExit(str(exc))
    directory = config.ROOT / 'backups'
    directory.mkdir(exist_ok=True)
    backup = directory / f'account-recovery-{time.time_ns()}.db'
    # Open the backup with private permissions before any sensitive data is written.
    import os
    descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    with sqlite3.connect(config.DB_PATH) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    with db(immediate=True) as conn:
        ensure_account_schema(conn)
        replace_password(conn, password, '服务器终端恢复登录密码')
    print('密码已重置，所有原登录已失效。用户名、绑定邮箱和数据加密密钥保持不变；无需重启服务。')
    print('备份：', backup)


if __name__ == '__main__':
    main()
