﻿param([switch]$Background, [switch]$CheckSyntax)
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
$process = Start-Process -FilePath $ps -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'sync-background.log') -RedirectStandardError (Join-Path $PSScriptRoot 'sync-background-error.log') -PassThru -Wait
$notice = New-Object -ComObject WScript.Shell
if ($process.ExitCode -eq 0) {
    $null = $notice.Popup('本次手动更新已完成。', 0, '晨的小助手', 64)
} else {
    $null = $notice.Popup('本次更新未完成，原版本已保留。请查看助手目录中的 sync-background.log 和 sync-background-error.log。', 0, '晨的小助手', 16)
}
if (-not $Background) { Write-Host '已取消自动启动，开始本次后台更新。以后双击 ManualUpdate。日志：sync-background.log' }
