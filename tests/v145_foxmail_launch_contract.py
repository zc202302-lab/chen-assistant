from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    helper = (ROOT / 'app/static/chen_foxmail_helper_v08.ps1').read_text(encoding='ascii')
    bootstrap = (ROOT / 'app/static/chen_foxmail_bootstrap.ps1').read_text(encoding='ascii')
    js = (ROOT / 'app/static/v123_foxmail_compose_fix.js').read_text(encoding='utf-8')
    route = (ROOT / 'app/v031_payment_workflow_routes.py').read_text(encoding='utf-8')
    workflow = (ROOT / '.github/workflows/windows-foxmail-helper.yml').read_text(encoding='utf-8')

    assert "$HelperVersion = '0.8'" in helper
    assert 'MAPISendMail' not in helper
    assert 'MAPI_LOGON_UI' not in helper
    assert 'System32\\mapi32.dll' not in helper
    assert 'Build-MailtoUri' in helper
    assert 'Start-Process -FilePath $foxmailExe -ArgumentList @($mailto)' in helper
    assert 'Wait-ComposeWindow' in helper
    assert 'Focus-Window' in helper
    assert 'Add-AttachmentViaDialog' in helper
    assert "SendWait('^+a')" in helper
    assert 'UIAutomationClient' in helper
    assert "AutomationIdProperty" in helper
    assert "'1148'" in helper
    assert "'1'" in helper
    assert "mode = 'foxmail-exe-mailto-dialog'" in helper
    assert "state = 'attachment-dialog-completed'" in helper
    assert 'launch_verified = $true' in helper
    assert 'attachment_dialog_verified = $true' in helper
    assert 'attachment_filename_exact = $true' in helper

    assert 'TcpListener([Net.IPAddress]::Loopback' in helper
    assert "AllowedRootDomain = 'ziboxiaozhushou.cn'" in helper
    assert 'Access-Control-Allow-Private-Network: true' in helper
    assert "Path -eq '/health'" in helper
    assert "launch_mode='foxmail-exe-mailto-dialog'" in helper
    assert "attachment_mode='file-dialog-uiautomation'" in helper
    assert 'mapi_required=$false' in helper

    assert 'chen_foxmail_helper_v08.ps1' in bootstrap
    assert "HelperVersion = '0.8'" in bootstrap
    assert 'Add-AttachmentViaDialog' in bootstrap
    assert "'-NoProfile', '-STA'" in bootstrap
    assert 'SysWOW64\\WindowsPowerShell\\v1.0\\powershell.exe' not in bootstrap
    assert 'Update-Helper' in bootstrap and 'Start-Watchdog' in bootstrap

    assert "bridgeFetch('/health'" in js
    assert "health?.version !== '0.8'" in js
    assert "health?.launch_mode !== 'foxmail-exe-mailto-dialog'" in js
    assert "health?.attachment_mode !== 'file-dialog-uiautomation'" in js
    assert 'health?.mapi_required !== false' in js
    assert 'result?.launch_verified !== true' in js
    assert 'result?.attachment_dialog_verified !== true' in js
    assert "result?.mode !== 'foxmail-exe-mailto-dialog'" in js
    assert "result?.state !== 'attachment-dialog-completed'" in js
    assert '__v146FoxmailDialogPrimary' in js

    for token in (
        'payment-mail-compose-v031', 'recipient_b64', 'subject_b64', 'body_b64',
        'attachment_filename_b64', 'attachment_content_base64',
    ):
        assert token in route, token

    assert 'pull_request:' in workflow
    assert 'chen_foxmail_helper_v08.ps1' in workflow

    print('v1.4.6 Foxmail v0.8 attachment-dialog contract passed')


if __name__ == '__main__':
    main()
