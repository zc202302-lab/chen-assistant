@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
py -3.11 -m pip install --disable-pip-version-check -r requirements.txt pyinstaller==6.16.0
if errorlevel 1 goto failed
py -3.11 -m PyInstaller --clean --noconfirm --onefile --name CloudMemberAddAgent member_add_agent.py
if errorlevel 1 goto failed
copy /y dist\CloudMemberAddAgent.exe . >nul
if errorlevel 1 goto failed
echo 已生成 CloudMemberAddAgent.exe。请与 start_agent.cmd 放在同一目录。
pause
exit /b 0
:failed
echo 构建失败。请确认已安装 Python 3.11 且可访问 Python 包索引。
pause
exit /b 1
