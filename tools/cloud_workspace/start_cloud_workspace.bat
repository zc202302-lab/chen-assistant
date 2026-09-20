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

python -c "import pystray, PIL" >nul 2>nul
if errorlevel 1 (
  echo 首次运行需要安装托盘组件...
  python -m pip install -r requirements-cloud-workspace.txt
  if errorlevel 1 (
    echo 托盘组件安装失败。程序仍可运行，但不会显示系统托盘图标。
  )
)

start "晨的小助手-云电脑工作区" pythonw cloud_workspace_switcher.py
if errorlevel 1 (
  python cloud_workspace_switcher.py
)
