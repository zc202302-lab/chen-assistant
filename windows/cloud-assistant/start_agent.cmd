@echo off
chcp 65001 >nul
title 晨的小助手 - 云电脑成员批量添加
setlocal
if exist "%~dp0CloudOfflineUpdater.exe" (
  "%~dp0CloudOfflineUpdater.exe" --bridge "Y:\ChenBridge"
) else if exist "%~dp0CloudMemberAddAgent.exe" (
  "%~dp0CloudMemberAddAgent.exe" --bridge "Y:\ChenBridge" --port 9222
) else (
  py -3.11 "%~dp0member_add_agent.py" --bridge "Y:\ChenBridge" --port 9222
)
if errorlevel 1 echo 云电脑助手已退出，请检查日志和共享目录中的结果文件。
pause

