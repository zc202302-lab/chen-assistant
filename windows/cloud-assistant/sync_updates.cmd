@echo off
chcp 65001 >nul
cd /d "%~dp0"
where gh >nul 2>nul
if errorlevel 1 (
  echo 请在本机安装 GitHub CLI，然后运行 gh auth login 完成登录。
  pause
  exit /b 1
)
set /p "bridge=请输入本机共享文件夹完整路径："
CloudOfflineUpdater.exe --sync --once --bridge "%bridge%"
pause
