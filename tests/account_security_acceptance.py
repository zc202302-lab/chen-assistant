"""Real browser recovery flow against an isolated server and mocked mail transport."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from unittest.mock import patch


def serve():
    import uvicorn
    from app.main import app

    def capture(email, code, purpose):
        path = Path(os.environ['TEST_ACCOUNT_MAIL_FILE'])
        rows = json.loads(path.read_text()) if path.exists() else []
        rows.append({'email': email, 'code': code, 'purpose': purpose})
        path.write_text(json.dumps(rows))
    with patch('app.account_mail.send_code', side_effect=capture), patch('app.account_routes.available', return_value=True):
        uvicorn.run(app, host='127.0.0.1', port=8187, log_level='warning')


def main():
    from v162_number_inbox_contract import ROOT, init_db
    from app import config
    from app.security import password_hash
    from cryptography.fernet import Fernet
    config.APP_PASSWORD_SALT = base64.urlsafe_b64encode(b'account-browser-salt').decode()
    config.APP_PASSWORD_HASH = password_hash('browser-original', config.APP_PASSWORD_SALT)
    os.environ.update({'APP_PASSWORD_SALT': config.APP_PASSWORD_SALT, 'APP_PASSWORD_HASH': config.APP_PASSWORD_HASH,
                       'APP_ENCRYPTION_KEY': Fernet.generate_key().decode()})
    init_db()
    mailbox = config.DB_PATH.parent / 'test-mailbox.json'
    os.environ['TEST_ACCOUNT_MAIL_FILE'] = str(mailbox)
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve'], cwd=ROOT, env=os.environ.copy())
    base = 'http://127.0.0.1:8187'
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + '/health', timeout=1)
                break
            except OSError:
                time.sleep(.1)
        else:
            raise AssertionError('test server did not start')
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width':1440, 'height':1000})
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(base + '/login')
            page.get_by_label('用户名', exact=True).fill(config.APP_USERNAME)
            page.get_by_label('密码', exact=True).fill('browser-original')
            page.get_by_role('button', name='登录', exact=True).click()
            page.locator('[data-sidebar-toggle]').click()
            page.get_by_role('link', name='账户与安全', exact=True).click()
            expect(page.get_by_role('heading', name='账户与安全', exact=True)).to_be_visible()
            page.locator('summary').filter(has_text='绑定找回邮箱').click()
            form = page.locator('form[action="/account/email/request"]')
            form.get_by_label('当前密码', exact=True).fill('browser-original')
            form.get_by_label('新找回邮箱', exact=True).fill('browser-owner@example.test')
            form.get_by_role('button', name='发送绑定验证码', exact=True).click()
            expect(page.get_by_role('heading', name='验证邮箱', exact=True)).to_be_visible()
            for _ in range(100):
                if mailbox.exists():
                    break
                time.sleep(.1)
            code = json.loads(mailbox.read_text())[-1]['code']
            form = page.locator('form[action="/account/email/confirm"]')
            form.get_by_label('当前密码', exact=True).fill('browser-original')
            form.get_by_label('邮箱验证码', exact=True).fill(code)
            form.get_by_role('button', name='验证并绑定邮箱', exact=True).click()
            expect(page.get_by_role('status')).to_contain_text('已验证并绑定')
            directory = ROOT / 'artifacts/account-security'
            directory.mkdir(parents=True, exist_ok=True)
            for width in [1440, 390]:
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.screenshot(path=str(directory / f'security-{width}.png'), full_page=True)
            csrf = page.locator('input[name=csrf]').first.input_value()
            context.request.post(base + '/logout', form={'csrf':csrf})
            page.goto(base + '/login')
            page.get_by_role('link', name='忘记密码？', exact=True).click()
            page.get_by_label('已绑定邮箱', exact=True).fill('browser-owner@example.test')
            page.get_by_role('button', name='发送重置验证码', exact=True).click()
            expect(page.get_by_role('heading', name='重置密码', exact=True)).to_be_visible()
            for _ in range(100):
                rows = json.loads(mailbox.read_text())
                if len(rows) >= 2:
                    break
                time.sleep(.1)
            page.get_by_label('已绑定邮箱', exact=True).fill('browser-owner@example.test')
            page.get_by_label('邮箱验证码', exact=True).fill(rows[-1]['code'])
            page.get_by_label('新密码', exact=True).fill('browser-reset')
            page.get_by_label('确认新密码', exact=True).fill('browser-mismatch')
            page.get_by_role('button', name='重置密码', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('不一致')
            # Sensitive fields are deliberately blank after any validation error.
            page.get_by_label('已绑定邮箱', exact=True).fill('browser-owner@example.test')
            page.get_by_label('邮箱验证码', exact=True).fill(rows[-1]['code'])
            page.get_by_label('新密码', exact=True).fill('browser-reset')
            page.get_by_label('确认新密码', exact=True).fill('browser-reset')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            page.get_by_role('button', name='重置密码', exact=True).click()
            expect(page).to_have_url(base + '/login?notice=password-updated')
            page.get_by_label('用户名', exact=True).fill(config.APP_USERNAME)
            page.get_by_label('密码', exact=True).fill('browser-reset')
            page.get_by_role('button', name='登录', exact=True).click()
            page.goto(base + '/account/security')
            page.locator('summary').filter(has_text='修改登录密码').click()
            form = page.locator('form[action="/account/password"]')
            form.get_by_label('当前密码', exact=True).fill('browser-reset')
            form.get_by_label('新密码', exact=True).fill('browser-final')
            form.get_by_label('确认新密码', exact=True).fill('browser-final')
            form.get_by_role('button', name='保存新密码', exact=True).click()
            expect(page).to_have_url(base + '/login?notice=password-updated')
            assert not errors, errors
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=10)
    print('account security browser passed: navigation, verified email, forgotten password, reset/login/change, desktop/mobile overflow; mocked SMTP only')


if __name__ == '__main__':
    if '--serve' in sys.argv:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        serve()
    else:
        main()
