@echo off
chcp 65001 >nul
title 晨的小助手 - 缴费查询诊断
echo.
echo 请确认：
echo 1. 已通过带9222参数的快捷方式打开Qaxbrowser
echo 2. 业务查询窗口保持打开
echo 3. http://127.0.0.1:9222/json/list 能看到10.19.89.56页面
echo.
set /p CHEN_QUERY=请输入要测试的账号或号码：
echo.
echo 本次仅填写账号并检测查询方式，不会点击“确定”，不会发起查询。
echo.
ChenPaymentQueryAgent.exe --inspect-query "%CHEN_QUERY%"
echo.
pause
