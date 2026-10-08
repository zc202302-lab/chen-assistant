param([string]$Bridge = 'E:\ChenBridge', [switch]$CheckProcess, [switch]$Once)
$ErrorActionPreference = 'Stop'
if (Test-Path 'C:\Program Files\GitHub CLI\gh.exe') { $env:PATH = 'C:\Program Files\GitHub CLI;' + $env:PATH }
if ($CheckProcess) {
    $null = & gh --version
    if ($LASTEXITCODE -ne 0) { throw 'GitHub CLI 进程验证失败' }
    Write-Host 'GitHub CLI 进程验证通过'
    exit 0
}
$updater = Join-Path $PSScriptRoot 'CloudOfflineUpdater.exe'
$next = Join-Path $PSScriptRoot 'CloudOfflineUpdater.next.exe'
if ((Test-Path -LiteralPath $next) -and -not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.update-rollback.json'))) {
    Move-Item -LiteralPath $next -Destination $updater -Force
}
if (-not (Test-Path -LiteralPath $updater)) { throw '缺少统一更新器，请保留完整安装目录。' }
# One canonical implementation; PowerShell only launches it and preserves exit status.
& $updater --sync --once --bridge $Bridge
exit $LASTEXITCODE
