@echo off
chcp 65001 >nul
title 晨的小助手 - 缴费查询代理
echo 正在监听 Y:\ChenBridge\requests ...
echo 保持本窗口运行；关闭窗口即停止自动查询。
echo.
ChenPaymentQueryAgent.exe --bridge "Y:\ChenBridge" --port 9222
echo.
echo 查询代理已停止。
pause
