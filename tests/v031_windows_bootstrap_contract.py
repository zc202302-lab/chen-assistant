from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    bootstrap_path = ROOT / 'app' / 'static' / 'chen_foxmail_bootstrap.ps1'
    bootstrap = bootstrap_path.read_text(encoding='ascii')
    for token in (
        "https://assistant.ziboxiaozhushou.cn/static/chen_foxmail_helper_v06.ps1",
        'Update-Helper', 'Start-Watchdog', 'Start-Bridge', 'Get-WatchProcesses',
        'Get-BridgePowerShell', 'SysWOW64\\WindowsPowerShell\\v1.0\\powershell.exe',
        'UpdateIntervalMinutes = 30', 'WatchIntervalSeconds = 20',
        'Invoke-WebRequest', 'Get-FileHash', 'Parser]::ParseFile',
        "chen_foxmail_helper.download.ps1", "chen_foxmail_helper.new.ps1",
        "ChenAssistant-Foxmail-Helper.lnk", "-Watch",
        "version='0.6'", 'Foxmail compose-window verification: enabled.',
    ):
        assert token in bootstrap, token

    assert all(b < 128 for b in bootstrap_path.read_bytes())

    helper_path = ROOT / 'app' / 'static' / 'chen_foxmail_helper_v06.ps1'
    helper = helper_path.read_text(encoding='ascii')
    for token in (
        "version='0.6'", 'MainWindowHandle', 'compose-window-detected',
        "System32\\mapi32.dll", 'MAPI_LOGON_UI|MAPI_DIALOG',
    ):
        assert token in helper, token
    assert 'MAPI_NEW_SESSION' not in helper
    assert all(b < 128 for b in helper_path.read_bytes())

    ui = (ROOT / 'app' / 'static' / 'v031_windows_bootstrap.js').read_text(encoding='utf-8')
    assert "/static/chen_foxmail_bootstrap.ps1" in ui
    assert '安装 Windows 助手（自动更新）' in ui
    assert '自动恢复运行' in ui

    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert '/static/v031_windows_bootstrap.js?v=0317' in base
    assert base.index('/static/v031_windows_bootstrap.js') > base.index('/static/v03_business_mail.js')

    main_py = (ROOT / 'app' / 'main.py').read_text(encoding='utf-8')
    assert "('.js', '.css', '.ps1')" in main_py

    print('v0.3.1/v0.6 Windows helper bootstrap contract passed')


if __name__ == '__main__':
    main()
