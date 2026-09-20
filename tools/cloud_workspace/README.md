# 云电脑工作区切换器

这是本机侧的小工具，直接复用“移动云电脑”客户端已有的低延迟远程通道，不使用共享文件夹或剪贴板做实时传输。

## 当前功能

- 一个主快捷键在“当前本机窗口 ↔ 云电脑”之间来回切换。
- 最大化、左停靠、右停靠、最小化均可单独设置快捷键。
- 图形化快捷键设置：点击输入框后直接按下组合键即可。
- 快捷键冲突检测。
- 启动后可自动隐藏到系统托盘。
- 托盘菜单可打开设置、执行一次切换、退出。
- 配置保存在 `cloud_workspace_config.json`。
- 可选“Windows 登录后自动启动”，无需管理员权限。
- 提供 `build_exe.bat`，可一键打包成单文件 EXE。

## 目标云电脑窗口

- 进程：`uSmartView_VDI_Client.exe`
- 兼容窗口标题：`我的电脑`

## 启动

双击：

```
start_cloud_workspace.bat
```

首次运行时，如果电脑里没有托盘组件，启动脚本会安装：

- `pystray`
- `Pillow`

安装完成后程序使用 `pythonw` 后台运行，不保留黑色 CMD 窗口。

## 默认快捷键

- `Ctrl+Alt+Space`：切到云电脑 / 返回刚才窗口
- `Ctrl+Alt+Enter`：云电脑最大化
- `Ctrl+Alt+Right`：停靠右侧
- `Ctrl+Alt+Left`：停靠左侧
- `Ctrl+Alt+Esc`：最小化并返回

所有快捷键都可以在设置窗口里修改。

## 支持的快捷键

修饰键：

- Ctrl
- Alt
- Shift
- Win

主按键：

- A-Z
- 0-9
- F1-F12
- Space
- Enter
- Left
- Right
- Esc

## 配置文件

```
cloud_workspace_config.json
```

即使不使用图形界面，也可以直接修改这个文件，保存后重新启动程序即可。


## 打包 EXE

双击：

```
build_exe.bat
```

完成后生成：

```
dist\晨的小助手-云电脑切换.exe
```

同时会复制：

```
dist\cloud_workspace_config.json
```

把这两个文件放在同一个文件夹即可。EXE 启用“Windows 登录后自动启动”后，会把当前 EXE 路径写入当前用户的启动项；如果之后移动 EXE，手动启动一次即可自动刷新路径。
