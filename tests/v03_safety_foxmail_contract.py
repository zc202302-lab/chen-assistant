from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    # Any v0.3 browser acceptance that starts the app or seeds data must opt into
    # an isolated APP_DB_PATH. This guards against ever repeating a production
    # deployment accidentally deleting data/app.db.
    acceptance_files = sorted((ROOT / 'tests').glob('v03*_acceptance.py'))
    assert acceptance_files, '未发现 v0.3 浏览器验收脚本'
    for path in acceptance_files:
        text = path.read_text(encoding='utf-8')
        assert 'APP_DB_PATH' in text, f'{path.name} 未配置隔离数据库'
        assert 'tempfile.TemporaryDirectory' in text, f'{path.name} 未使用临时目录'
        assert '.unlink()' not in text, f'{path.name} 仍包含删除数据库/文件操作'

    config = (ROOT / 'app' / 'config.py').read_text(encoding='utf-8')
    assert 'APP_DB_PATH' in config
    assert 'DB_PATH = Path(_db_override)' in config

    js = (ROOT / 'app' / 'static' / 'v03_business_mail.js').read_text(encoding='utf-8')
    assert "FOXMAIL_BRIDGE = 'http://127.0.0.1:18763'" in js
    assert 'openWithLocalFoxmail' in js
    assert 'downloadBlob' in js
    assert '未检测到 Windows 助手' in js
    assert '/static/chen_foxmail_helper.ps1' in js
    assert "fd.append('recipient'" in js

    foxmail_action = (ROOT / 'app' / 'static' / 'v03_foxmail_action_fix.js').read_text(encoding='utf-8')
    assert "FOXMAIL_BRIDGE = 'http://127.0.0.1:18763'" in foxmail_action
    assert "button.disabled = false" in foxmail_action
    assert '当前客户本月缴费流程尚未完成' in foxmail_action
    assert '正在准备邮件' in foxmail_action
    assert "payment-mail-compose-v03" in foxmail_action
    assert "payment-mail-draft-v03" in foxmail_action
    assert "'/compose'" in foxmail_action and "method: 'POST'" in foxmail_action
    assert 'Windows助手版本较旧' in foxmail_action

    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert '/static/v03_foxmail_action_fix.js?v=0306' in base

    helper = (ROOT / 'app' / 'static' / 'chen_foxmail_helper.ps1').read_text(encoding='utf-8')
    assert 'BridgeMode' in helper and 'TcpListener' in helper
    assert 'ComposeRequest' in helper and 'Invoke-FoxmailCompose' in helper
    assert 'Get-FoxmailMapiDll' in helper
    assert 'FMMAPI32' not in helper or 'Foxmail' in helper
    assert 'LoadLibrary' in helper and 'GetProcAddress' in helper
    assert 'MAPISendMail' in helper and 'MAPI_DIALOG' in helper
    assert "Path -eq '/compose'" in helper
    assert "version = '0.4'" in helper and 'compose = $true' in helper
    assert 'foxmail_direct' in helper
    assert 'SysWOW64\\WindowsPowerShell' in helper
    assert "AllowedRootDomain = 'ziboxiaozhushou.cn'" in helper
    assert 'Access-Control-Allow-Private-Network: true' in helper
    assert 'Start-Process -FilePath $path' in helper  # legacy .eml fallback remains
    assert 'Get-CimInstance Win32_Process' in helper  # installer replaces old bridge process
    assert 'Startup' in helper

    bridge = (ROOT / 'windows' / 'foxmail_bridge.ps1').read_text(encoding='utf-8')
    installer = (ROOT / 'windows' / 'install_foxmail_bridge.ps1').read_text(encoding='utf-8')
    assert 'IPAddress]::Loopback' in bridge or 'IPAddress]::IsLoopback' in bridge
    assert "AllowedRootDomain = 'ziboxiaozhushou.cn'" in bridge
    assert 'Access-Control-Allow-Private-Network: true' in bridge
    assert "Path -eq '/open'" in bridge
    assert '[IO.File]::WriteAllBytes' in bridge and 'Start-Process' in bridge
    assert 'Startup' in installer and 'foxmail_bridge.ps1' in installer

    mail_routes = (ROOT / 'app' / 'v03_mail_draft_routes.py').read_text(encoding='utf-8')
    assert "RECIPIENT_META_KEY = 'payment_mail_recipient_v03'" in mail_routes
    assert '_save_recipient' in mail_routes
    assert "recipient: str = Form('')" in mail_routes
    assert "payment-mail-compose-v03" in mail_routes
    assert 'attachment_content_base64' in mail_routes

    main_py = (ROOT / 'app' / 'main.py').read_text(encoding='utf-8')
    assert "connect-src 'self' http://127.0.0.1:18763 http://localhost:18763" in main_py
    assert "('.js', '.css', '.ps1')" in main_py

    deploy = (ROOT / 'deploy.sh').read_text(encoding='utf-8')
    assert 'tests/v03_' not in deploy, '生产 deploy.sh 不得执行 v0.3 测试脚本'

    print('v0.3 safety/Foxmail contract passed')


if __name__ == '__main__':
    main()
