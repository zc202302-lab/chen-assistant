# Foxmail bootstrap `irm | iex` install fix

## Problem

The Windows installation command is intentionally simple:

```powershell
irm https://assistant.ziboxiaozhushou.cn/static/chen_foxmail_bootstrap.ps1 | iex
```

When PowerShell executes a script from pipeline text through `Invoke-Expression`, `$PSCommandPath` is empty. The previous bootstrap assumed `$PSCommandPath` was always a real file path and called `GetFullPath($PSCommandPath)`, causing installation to fail before the v0.7 helper was written to disk.

## Fix

The bootstrap now supports both launch forms:

- script executed from a real `.ps1` file: copy the current file into `%LOCALAPPDATA%\ChenAssistant`;
- script executed through `irm ... | iex`: download a validated copy of the bootstrap itself into `%LOCALAPPDATA%\ChenAssistant` before creating the startup shortcut and watchdog.

The downloaded bootstrap is checked for minimum size, ASCII safety, and Windows PowerShell syntax before it is installed.

This does not change the Foxmail v0.7 launch design: the helper still uses direct `Foxmail.exe + mailto`, verifies the compose window, focuses it, and attaches the customer TXT through clipboard file-drop.