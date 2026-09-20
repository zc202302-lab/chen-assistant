@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo 未找到 Python。
  pause
  exit /b 1
)

echo [1/3] 安装打包依赖...
python -m pip install --upgrade pyinstaller pystray Pillow
if errorlevel 1 goto :fail

echo [2/3] 清理旧产物...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist cloud_workspace_switcher.spec del /q cloud_workspace_switcher.spec

echo [3/3] 生成 EXE...
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "晨的小助手-云电脑切换" ^
  --collect-all pystray ^
  --collect-all PIL ^
  cloud_workspace_switcher.py

if errorlevel 1 goto :fail

copy /y cloud_workspace_config.json "dist\cloud_workspace_config.json" >nul
echo.
echo 打包完成：
echo %CD%\dist\晨的小助手-云电脑切换.exe
echo.
echo 将 EXE 和 cloud_workspace_config.json 放在同一文件夹即可使用。
pause
exit /b 0

:fail
echo.
echo 打包失败，请把本窗口错误信息发给我。
pause
exit /b 1
