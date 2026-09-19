@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ===== 晨的小助手：云电脑镜像端 =====
echo.
set /p SHARE=请输入云电脑看到的共享文件夹路径（例如 Z:\ChenMirror）：
if "%SHARE%"=="" (
  echo 未输入路径。
  pause
  exit /b 1
)
where python >nul 2>nul
if errorlevel 1 (
  echo 未找到 Python。请先确认云电脑已安装 Python 并已加入 PATH。
  pause
  exit /b 1
)
python cloud_shared_agent.py --shared-dir "%SHARE%" --mode active --fps 6
pause
