@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在只读检查业务页面，请稍候……
CloudMemberAddAgent.exe --diagnose-browser > browser-diagnosis.txt 2>&1
start "" notepad.exe "%~dp0browser-diagnosis.txt"
echo 诊断结果已用记事本打开，请全选复制并发送。
pause
