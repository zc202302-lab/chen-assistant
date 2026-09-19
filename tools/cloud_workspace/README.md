# 云电脑工作区切换器

这个方案不重新编码云电脑画面，也不使用共享文件夹或剪贴板做实时链路，而是直接复用“移动云电脑”客户端现有的低延迟远程通道。

## 识别目标

- 进程：`uSmartView_VDI_Client.exe`
- 兼容窗口标题：`我的电脑`

## 自定义快捷键

快捷键配置文件：

```
cloud_workspace_config.json
```

默认：

```json
{
  "toggle": "Ctrl+Alt+Space",
  "maximize": "Ctrl+Alt+Enter",
  "dock_right": "Ctrl+Alt+Right",
  "dock_left": "Ctrl+Alt+Left",
  "minimize": "Ctrl+Alt+Esc"
}
```

你可以直接修改这些值，保存后重启切换器即可生效。

支持：

- 修饰键：`Ctrl`、`Alt`、`Shift`、`Win`
- 主按键：`A-Z`、`0-9`、`F1-F12`、`Space`、`Enter`、`Left`、`Right`、`Esc`

例如把主切换改成 `Alt+Q`：

```json
"toggle": "Alt+Q"
```

如果某个快捷键被其他软件占用，程序启动时会直接提示冲突的快捷键。

## 启动

双击：

```
start_cloud_workspace.bat
```

或运行：

```bat
python cloud_workspace_switcher.py
```

这套方案完全运行在本机，不要求云电脑访问公网，也不会修改移动云电脑的网络协议。
