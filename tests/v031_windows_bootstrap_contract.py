from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    bootstrap_path = ROOT / 'app' / 'static' / 'chen_foxmail_bootstrap.ps1'
    bootstrap = bootstrap_path.read_text(encoding='ascii')
    for token in (
        "https://assistant.ziboxiaozhushou.cn/static/chen_foxmail_bootstrap.ps1",
        "https://assistant.ziboxiaozhushou.cn/static/chen_foxmail_helper_v08.ps1",
        'Update-Helper', 'Start-Watchdog', 'Start-Bridge', 'Get-WatchProcesses',
        'Get-BridgePowerShell', 'System32\\WindowsPowerShell\\v1.0\\powershell.exe',
        'UpdateIntervalMinutes = 30', 'WatchIntervalSeconds = 20',
        'Invoke-WebRequest', 'Get-FileHash', 'Parser]::ParseFile',
        "chen_foxmail_bootstrap.download.ps1",
        "chen_foxmail_helper.download.ps1", "chen_foxmail_helper.new.ps1",
        "if ($PSCommandPath -and (Test-Path -LiteralPath $PSCommandPath))",
        "$uri = $BootstrapUrl + '?install='",
        'Copy-Item -Force -LiteralPath $download -Destination $BootstrapPath',
        "ChenAssistant-Foxmail-Helper.lnk", "-Watch",
        "HelperVersion = '0.8'", 'Build-MailtoUri', 'Add-AttachmentViaDialog',
        'UIAutomationClient',
        'Simple MAPI and compose-window file paste are not used by v0.8.',
    ):
        assert token in bootstrap, token
    assert 'GetFullPath($PSCommandPath)' in bootstrap
    assert 'SysWOW64\\WindowsPowerShell\\v1.0\\powershell.exe' not in bootstrap
    assert all(b < 128 for b in bootstrap_path.read_bytes())

    helper_path = ROOT / 'app' / 'static' / 'chen_foxmail_helper_v08.ps1'
    helper = helper_path.read_text(encoding='ascii')
    for token in (
        "$HelperVersion = '0.8'",
        "launch_mode='foxmail-exe-mailto-dialog'",
        "attachment_mode='file-dialog-uiautomation'",
        'Build-MailtoUri', 'Add-AttachmentViaDialog', 'Focus-Window',
        'Start-Process -FilePath $foxmailExe -ArgumentList @($mailto)',
        "mode = 'foxmail-exe-mailto-dialog'",
        "state = 'attachment-dialog-completed'",
        'attachment_dialog_verified = $true',
        'mapi_required=$false',
    ):
        assert token in helper, token
    assert 'MAPISendMail' not in helper
    assert 'MAPI_LOGON_UI' not in helper
    assert all(b < 128 for b in helper_path.read_bytes())

    ui = (ROOT / 'app' / 'static' / 'v031_windows_bootstrap.js').read_text(encoding='utf-8')
    assert "/static/chen_foxmail_bootstrap.ps1" in ui
    assert '安装 Windows 助手（自动更新）' in ui
    assert '自动恢复运行' in ui

    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert '/static/v031_windows_bootstrap.js?v=0317' in base
    assert base.index('/static/v031_windows_bootstrap.js') > base.index('/static/v03_business_mail.js')
    assert '/static/v123_foxmail_compose_fix.js?v=1460' in base

    main_py = (ROOT / 'app' / 'main.py').read_text(encoding='utf-8')
    assert "('.js', '.css', '.ps1')" in main_py

    print('v0.3.1/v0.8 Windows helper bootstrap contract passed')


if __name__ == '__main__':
    main()
