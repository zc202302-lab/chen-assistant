@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist "dist\晨的小助手-云电脑切换.exe" (
  echo 尚未生成 EXE，请先双击 build_exe.bat。
  pause
  exit /b 1
)

start "" "dist\晨的小助手-云电脑切换.exe"
exit /b 0
