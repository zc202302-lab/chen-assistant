from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    helper = (ROOT / 'app/static/chen_foxmail_helper_v09.ps1').read_text(encoding='ascii')
    bootstrap = (ROOT / 'app/static/chen_foxmail_bootstrap.ps1').read_text(encoding='ascii')
    js = (ROOT / 'app/static/v123_foxmail_compose_fix.js').read_text(encoding='utf-8')
    route = (ROOT / 'app/v031_payment_workflow_routes.py').read_text(encoding='utf-8')
    workflow = (ROOT / '.github/workflows/windows-foxmail-helper.yml').read_text(encoding='utf-8')

    # Primary launch remains direct Foxmail.exe + mailto. The helper prepares the
    # exact TXT, verifies its SHA256, places it on the Windows file-drop clipboard,
    # and leaves Ctrl+V attachment/send decisions to the user.
    assert "$HelperVersion = '0.9'" in helper
    assert 'MAPISendMail' not in helper
    assert 'MAPI_LOGON_UI' not in helper
    assert 'System32\\mapi32.dll' not in helper
    assert 'Build-MailtoUri' in helper
    assert 'Start-Process -FilePath $foxmailExe -ArgumentList @($mailto)' in helper
    assert 'Wait-ComposeWindow' in helper
    assert 'Set-AttachmentClipboard' in helper
    assert '[System.Windows.Forms.Clipboard]::SetFileDropList' in helper
    assert "Start-Process -FilePath 'explorer.exe'" not in helper
    assert 'UIAutomationClient' not in helper
    assert "SendWait('^+a')" not in helper
    assert "SendWait('^v')" not in helper
    assert "mode = 'foxmail-exe-mailto-clipboard-ready'" in helper
    assert "state = 'draft-open-clipboard-ready'" in helper
    assert 'launch_verified = $true' in helper
    assert 'attachment_file_verified = $true' in helper
    assert 'attachment_clipboard_verified = $true' in helper
    assert 'attachment_integrity_verified = $true' in helper
    assert 'explorer_dispatched = $false' in helper
    assert 'attachment_filename_exact = $true' in helper

    # Security boundary stays loopback-only with strict web origin checks.
    assert 'TcpListener([Net.IPAddress]::Loopback' in helper
    assert "AllowedRootDomain = 'ziboxiaozhushou.cn'" in helper
    assert 'Access-Control-Allow-Private-Network: true' in helper
    assert "Path -eq '/health'" in helper
    assert "launch_mode='foxmail-exe-mailto-clipboard-ready'" in helper
    assert "attachment_mode='clipboard-file-drop'" in helper
    assert 'auto_send=$false' in helper
    assert 'mapi_required=$false' in helper

    # Bootstrap must auto-update to the v0.9 helper in the signed-in desktop.
    assert 'chen_foxmail_helper_v09.ps1' in bootstrap
    assert "HelperVersion = '0.9'" in bootstrap
    assert 'Set-AttachmentClipboard' in bootstrap
    assert "attachment_mode='clipboard-file-drop'" in bootstrap
    assert "'-NoProfile', '-STA'" in bootstrap
    assert 'SysWOW64\\WindowsPowerShell\\v1.0\\powershell.exe' not in bootstrap
    assert 'Update-Helper' in bootstrap and 'Start-Watchdog' in bootstrap

    # Browser refuses stale helpers and only marks preparation successful after
    # both the Foxmail draft and the local TXT handoff have been verified.
    assert "bridgeFetch('/health'" in js
    assert "health?.version !== '0.9'" in js
    assert "health?.launch_mode !== 'foxmail-exe-mailto-clipboard-ready'" in js
    assert "health?.attachment_mode !== 'clipboard-file-drop'" in js
    assert 'health?.auto_send !== false' in js
    assert 'health?.mapi_required !== false' in js
    assert 'result?.launch_verified !== true' in js
    assert 'result?.attachment_file_verified !== true' in js
    assert 'result?.attachment_clipboard_verified !== true' in js
    assert 'result?.attachment_integrity_verified !== true' in js
    assert 'result?.explorer_dispatched !== false' in js
    assert "result?.mode !== 'foxmail-exe-mailto-clipboard-ready'" in js
    assert "result?.state !== 'draft-open-clipboard-ready'" in js
    assert '__v159FoxmailClipboardAttachment' in js
    assert 'TXT已复制到文件剪贴板' in js

    # Existing customer-specific mail template and exact TXT payload stay intact.
    for token in (
        'payment-mail-compose-v031', 'recipient_b64', 'subject_b64', 'body_b64',
        'attachment_filename_b64', 'attachment_content_base64',
    ):
        assert token in route, token

    assert 'pull_request:' in workflow
    assert 'chen_foxmail_helper_v09.ps1' in workflow

    print('v1.5.9 Foxmail clipboard-attachment contract passed')


if __name__ == '__main__':
    main()
