from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / 'app' / 'static' / 'chen_foxmail_bootstrap.ps1'
    text = path.read_text(encoding='ascii')

    required = (
        "$BootstrapUrl = 'https://assistant.ziboxiaozhushou.cn/static/chen_foxmail_bootstrap.ps1'",
        'if ($PSCommandPath -and (Test-Path -LiteralPath $PSCommandPath))',
        "chen_foxmail_bootstrap.download.ps1",
        "$uri = $BootstrapUrl + '?install=' + [DateTime]::UtcNow.Ticks",
        'Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $download -TimeoutSec 20',
        "throw 'Downloaded bootstrap is unexpectedly small.'",
        "throw 'Downloaded bootstrap is not ASCII-safe.'",
        "throw 'Downloaded bootstrap failed PowerShell syntax validation.'",
        'Copy-Item -Force -LiteralPath $download -Destination $BootstrapPath',
    )
    for token in required:
        assert token in text, token

    assert text.index('if ($PSCommandPath -and') < text.index('[IO.Path]::GetFullPath($PSCommandPath)')
    assert all(b < 128 for b in path.read_bytes())
    print('Foxmail bootstrap irm-pipe-iex install contract passed')


if __name__ == '__main__':
    main()
