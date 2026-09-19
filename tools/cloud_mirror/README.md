# 云电脑网页镜像（共享文件夹模式）

适用于“云电脑不能访问公网，但云电脑与本机可以共享文件夹、复制粘贴内容/文件”的环境。

## 架构

- 云电脑运行 `cloud_shared_agent.py`：截取当前窗口或完整桌面，把最新画面写入共享文件夹，并读取本机写入的键鼠指令。
- 本机运行 `host_shared_bridge.py`：只在 `127.0.0.1` 提供网页；Chrome 从本机服务读取共享目录中的画面，并把操作写回共享目录。
- 不需要云电脑联网，不需要云电脑监听 TCP 端口，也不需要 VPS。

## 第一次测试

假设同一个共享目录：

- 云电脑看到：`Z:\\ChenMirror`
- 本机看到：`D:\\CloudShare\\ChenMirror`

两端路径可以不同，只要实际指向同一个共享目录。

云电脑：

```bat
cd /d <仓库目录>\tools\cloud_mirror
python cloud_shared_agent.py --shared-dir "Z:\ChenMirror" --mode active --fps 6
```

本机：

```bat
cd /d <仓库目录>\tools\cloud_mirror
python host_shared_bridge.py --shared-dir "D:\CloudShare\ChenMirror"
```

然后本机 Chrome 打开：

```
http://127.0.0.1:18765/
```

默认只看。勾选“允许控制”后，鼠标、键盘、滚轮和文本粘贴会写入共享目录，由云电脑执行。

## 说明

- `--mode active` 只镜像云电脑当前前台窗口，更接近“网页镜像”。
- `--mode screen` 镜像完整桌面。
- 共享文件夹同步速度决定实际帧率。第一版默认 6 FPS，优先验证可用性；后续再做增量画面编码和更低延迟。
- 这套链路不把云电脑内网代理到本机，只传输画面和输入事件。
