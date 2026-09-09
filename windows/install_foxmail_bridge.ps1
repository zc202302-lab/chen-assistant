$ErrorActionPreference = 'Stop'

$Source = Join-Path $PSScriptRoot 'foxmail_bridge.ps1'
if (-not (Test-Path $Source)) {
    Write-Host '未找到 foxmail_bridge.ps1，请确保两个文件放在同一文件夹。' -ForegroundColor Red
    exit 1
}

$InstallDir = Join-Path $env:LOCALAPPDATA 'ChenAssistant'
$Target = Join-Path $InstallDir 'foxmail_bridge.ps1'
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -Force $Source $Target

$Startup = [Environment]::GetFolderPath('Startup')
$ShortcutPath = Join-Path $Startup '晨的助手-Foxmail桥接.lnk'
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = 'powershell.exe'
$Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Target`""
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Description = '晨的助手 Foxmail 本地桥接'
$Shortcut.Save()

# Start immediately. A second launch is harmless: it exits when the loopback port
# is already occupied by the existing bridge instance.
Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', "`"$Target`""
)

Start-Sleep -Milliseconds 700
Write-Host ''
Write-Host '晨的助手 Foxmail 本地助手已安装。' -ForegroundColor Green
Write-Host "安装位置：$Target"
Write-Host '它会随 Windows 登录自动启动，只监听本机 127.0.0.1:18763。'
Write-Host ''
Write-Host '重要：请确保 Windows 的 .eml 文件默认使用 Foxmail 打开。'
Write-Host '回到晨的助手网页后刷新页面，邮件模板中应显示“Windows 助手已连接”。'
