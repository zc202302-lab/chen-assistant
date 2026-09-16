from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    helper = (ROOT / 'app/static/chen_foxmail_helper_v07.ps1').read_text(encoding='ascii')
    bootstrap = (ROOT / 'app/static/chen_foxmail_bootstrap.ps1').read_text(encoding='ascii')
    js = (ROOT / 'app/static/v123_foxmail_compose_fix.js').read_text(encoding='utf-8')
    route = (ROOT / 'app/v031_payment_workflow_routes.py').read_text(encoding='utf-8')
    workflow = (ROOT / '.github/workflows/windows-foxmail-helper.yml').read_text(encoding='utf-8')

    # Primary Windows launch path must not depend on Simple MAPI anymore.
    assert "$HelperVersion = '0.7'" in helper
    assert 'MAPISendMail' not in helper
    assert 'MAPI_LOGON_UI' not in helper
    assert 'System32\\mapi32.dll' not in helper
    assert 'Build-MailtoUri' in helper
    assert 'Start-Process -FilePath $foxmailExe -ArgumentList @($mailto)' in helper
    assert 'Wait-ComposeWindow' in helper
    assert 'Focus-ComposeWindow' in helper
    assert 'Clipboard]::SetFileDropList' in helper
    assert "SendWait('^v')" in helper
    assert "mode = 'foxmail-exe-mailto-clipboard'" in helper
    assert "state = 'compose-window-detected'" in helper
    assert 'launch_verified = $true' in helper
    assert 'clipboard_verified = $true' in helper
    assert 'attachment_filename_exact = $true' in helper

    # Loopback-only bridge and origin restrictions remain mandatory.
    assert 'TcpListener([Net.IPAddress]::Loopback' in helper
    assert "AllowedRootDomain = 'ziboxiaozhushou.cn'" in helper
    assert 'Access-Control-Allow-Private-Network: true' in helper
    assert "Path -eq '/health'" in helper
    assert "launch_mode='foxmail-exe-mailto'" in helper
    assert 'mapi_required=$false' in helper

    # Bootstrap must install and watchdog v0.7 in an STA desktop process.
    assert 'chen_foxmail_helper_v07.ps1' in bootstrap
    assert "'-NoProfile', '-STA'" in bootstrap
    assert 'SysWOW64\\WindowsPowerShell\\v1.0\\powershell.exe' not in bootstrap
    assert 'Update-Helper' in bootstrap and 'Start-Watchdog' in bootstrap

    # Browser refuses stale MAPI helpers and advances only after verified compose.
    assert "bridgeFetch('/health'" in js
    assert "health?.version !== '0.7'" in js
    assert "health?.launch_mode !== 'foxmail-exe-mailto'" in js
    assert 'health?.mapi_required !== false' in js
    assert 'result?.launch_verified !== true' in js
    assert "result?.mode !== 'foxmail-exe-mailto-clipboard'" in js
    assert "result?.state !== 'compose-window-detected'" in js
    assert '__v145FoxmailExePrimary' in js

    # Existing server-side customer mail template and exact TXT payload stay intact.
    for token in (
        'payment-mail-compose-v031', 'recipient_b64', 'subject_b64', 'body_b64',
        'attachment_filename_b64', 'attachment_content_base64',
    ):
        assert token in route, token

    # Windows PowerShell 5.1 checks run on PRs before merge.
    assert 'pull_request:' in workflow
    assert 'chen_foxmail_helper_v07.ps1' in workflow

    print('v1.4.5 Foxmail v0.7 launch contract passed')


if __name__ == '__main__':
    main()
