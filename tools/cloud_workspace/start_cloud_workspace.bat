@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo 未找到 Python。请先确认本机 Python 已安装并加入 PATH。
  pause
  exit /b 1
)

start "晨的小助手-云电脑工作区" /min python cloud_workspace_switcher.py
echo 已启动云电脑工作区切换器。
echo.
echo Ctrl+Alt+Space   切到云电脑 / 返回
echo Ctrl+Alt+Enter   最大化云电脑
echo Ctrl+Alt+Right   停靠右侧
echo Ctrl+Alt+Left    停靠左侧
echo Ctrl+Alt+Esc     最小化云电脑并返回
timeout /t 4 >nul
