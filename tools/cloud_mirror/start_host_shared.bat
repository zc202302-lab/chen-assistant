@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ===== 晨的小助手：本机浏览器镜像桥 =====
echo.
set /p SHARE=请输入本机看到的同一个共享文件夹路径：
if "%SHARE%"=="" (
  echo 未输入路径。
  pause
  exit /b 1
)
where python >nul 2>nul
if errorlevel 1 (
  echo 未找到 Python。请先确认本机已安装 Python 并已加入 PATH。
  pause
  exit /b 1
)
start "" http://127.0.0.1:18765/
python host_shared_bridge.py --shared-dir "%SHARE%"
pause
