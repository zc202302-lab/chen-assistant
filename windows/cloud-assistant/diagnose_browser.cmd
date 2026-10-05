@echo off
chcp 65001 >nul
cd /d "%~dp0"
CloudMemberAddAgent.exe --diagnose-browser
pause
