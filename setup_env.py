from pathlib import Path
import base64, hashlib, secrets, getpass
from cryptography.fernet import Fernet

root = Path(__file__).resolve().parent
env = root / '.env'
if env.exists():
    ans = input('.env 已存在，覆盖？输入 YES 继续：').strip()
    if ans != 'YES':
        raise SystemExit('已取消')
username = input('登录用户名 [晨]：').strip() or '晨'
while True:
    p1 = getpass.getpass('设置登录密码：')
    p2 = getpass.getpass('再次输入登录密码：')
    if p1 and p1 == p2:
        break
    print('两次密码不一致或密码为空，请重试。')
salt = secrets.token_bytes(16)
raw = hashlib.scrypt(p1.encode('utf-8'), salt=salt, n=2**14, r=8, p=1, dklen=32)
text = '\n'.join([
    f'APP_USERNAME={username}',
    f'APP_PASSWORD_SALT={base64.urlsafe_b64encode(salt).decode()}',
    f'APP_PASSWORD_HASH={base64.urlsafe_b64encode(raw).decode()}',
    f'APP_SESSION_SECRET={secrets.token_urlsafe(48)}',
    f'APP_ENCRYPTION_KEY={Fernet.generate_key().decode()}',
    'APP_SECURE_COOKIE=1',
    'APP_BASE_URL=',
    '',
])
env.write_text(text, encoding='utf-8')
try:
    env.chmod(0o600)
except Exception:
    pass
print('已生成 .env。请勿上传 GitHub。')
