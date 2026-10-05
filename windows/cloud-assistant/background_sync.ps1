param([switch]$Background, [switch]$CheckSyntax)
$ErrorActionPreference = 'Stop'
if ($CheckSyntax) { exit 0 }
$sync = Join-Path $PSScriptRoot 'sync_updates.ps1'
if (-not (Test-Path -LiteralPath $sync)) { throw '找不到 sync_updates.ps1，请放在同一个助手文件夹。' }
$ps = Join-Path $PSHOME 'powershell.exe'
if (-not $Background) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'ChenCloudUpdateSync.lnk'))
    $shortcut.TargetPath = $ps
    $shortcut.Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -Background'
    $shortcut.WorkingDirectory = $PSScriptRoot
    $shortcut.WindowStyle = 7
    $shortcut.Save()
}
$arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $sync + '" -Bridge "E:\ChenBridge"'
Start-Process -FilePath $ps -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'sync-background.log') -RedirectStandardError (Join-Path $PSScriptRoot 'sync-background-error.log') | Out-Null
if (-not $Background) { Write-Host '已开启后台同步并设置登录后自动启动。可以关闭此窗口。日志：sync-background.log' }
