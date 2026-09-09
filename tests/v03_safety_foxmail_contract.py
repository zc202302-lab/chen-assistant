from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    # Any v0.3/v0.3.1 browser acceptance that starts the app or seeds data must opt into
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
    assert "'/compose'" in foxmail_action and "method: 'POST'" in foxmail_action
    assert 'verified_dispatch === true' in foxmail_action
    assert 'data.verified !== true' in foxmail_action
    assert 'Foxmail写邮件窗口已确认打开' in foxmail_action
    assert '本次不会自动下载.eml' in foxmail_action
    assert '本次未自动下载.eml' in foxmail_action
    assert 'downloadEmlFallback' not in foxmail_action
    assert 'payment-mail-draft-v03' not in foxmail_action

    v031 = (ROOT / 'app' / 'static' / 'v031_payment_workflow.js').read_text(encoding='utf-8')
    assert 'payment-mail-compose-v031' in v031
    assert '发送邮件后回到这里点击“发起缴费”' in v031
    assert "FOXMAIL_BRIDGE = 'http://127.0.0.1:18763'" in v031

    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert '/static/v03_foxmail_action_fix.js?v=0311' in base
    assert '/static/v031_payment_workflow.js?v=0311' in base
    assert '/static/v031_amount_rollback_fix.js?v=0314' in base
    assert '/static/v031_workflow_actions.js?v=0314' in base
    assert '/static/v031_workflow_runtime_fix.js?v=0314' in base
    assert '/static/v031_workflow_dom_guard.js?v=0314' in base

    helper = (ROOT / 'app' / 'static' / 'chen_foxmail_helper.ps1').read_text(encoding='utf-8')
    assert 'BridgeMode' in helper and 'TcpListener' in helper
    assert 'ComposeRequest' in helper and 'Invoke-FoxmailCompose' in helper
    assert 'Get-FoxmailExe' in helper
    assert 'Build-MailtoUri' in helper and "'mailto:'" in helper
    assert 'Clipboard]::SetFileDropList' in helper
    assert "SendWait('^v')" in helper
    assert 'SetForegroundWindow' in helper and 'GetFoxmailWindows' in helper
    assert "Path -eq '/compose'" in helper
    assert "version = '0.7'" in helper and 'compose = $true' in helper
    assert "compose_mode = 'mailto-clipboard'" in helper
    assert 'foxmail_direct' in helper and 'verified_dispatch' in helper
    assert 'attachment_filename_exact = $true' in helper
    assert '$composeDir = Join-Path $MailDir $prefix' in helper
    assert '$attachmentPath = Join-Path $composeDir $attachmentName' in helper
    assert "($prefix + '-' + $attachmentName)" not in helper
    assert "'-STA'" in helper
    assert "AllowedRootDomain = 'ziboxiaozhushou.cn'" in helper
    assert 'Access-Control-Allow-Private-Network: true' in helper
    assert 'Start-Process -FilePath $path' in helper
    assert 'Get-CimInstance Win32_Process' in helper
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

    print('v0.3.1 safety/Foxmail contract passed')


if __name__ == '__main__':
    main()
