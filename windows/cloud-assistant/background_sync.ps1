param([switch]$Background, [switch]$CheckSyntax)
$ErrorActionPreference = 'Stop'
if ($CheckSyntax) { exit 0 }
$sync = Join-Path $PSScriptRoot 'sync_updates.ps1'
if (-not (Test-Path -LiteralPath $sync)) { throw '找不到 sync_updates.ps1，请放在同一个助手文件夹。' }
$ps = Join-Path $PSHOME 'powershell.exe'
$startupLink = Join-Path ([Environment]::GetFolderPath('Startup')) 'ChenCloudUpdateSync.lnk'
if (Test-Path -LiteralPath $startupLink) { Remove-Item -LiteralPath $startupLink -Force }
# Stop only a previous synchronizer from this same installation.
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object {
    $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine.Contains('"' + $sync + '"')
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
if (-not $Background) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path $PSScriptRoot 'ManualUpdate.lnk'))
    $shortcut.TargetPath = $ps
    $shortcut.Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -Background'
    $shortcut.WorkingDirectory = $PSScriptRoot
    $shortcut.WindowStyle = 7
    $shortcut.Save()
}
$arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $sync + '" -Bridge "E:\ChenBridge" -Once'
Start-Process -FilePath $ps -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'sync-background.log') -RedirectStandardError (Join-Path $PSScriptRoot 'sync-background-error.log') | Out-Null
if (-not $Background) { Write-Host '已取消自动启动，开始本次后台更新。以后双击 ManualUpdate。日志：sync-background.log' }
