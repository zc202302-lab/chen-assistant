from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import secrets
import socket
import struct
import threading
import time
import urllib.parse
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if __import__("sys").platform != "win32":
    raise SystemExit("cloud_mirror_agent.py 仅支持 Windows。")

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Win32 API declarations are explicit because the default ctypes return type is
# 32-bit int. GDI/HANDLE values are pointer-sized on 64-bit Windows.
ULONG_PTR = ctypes.c_size_t
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.restype = wintypes.BOOL
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.CloseClipboard.restype = wintypes.BOOL

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.BitBlt.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL

kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
BI_RGB = 0
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

VK_SPECIAL = {
    "Backspace": 0x08,
    "Tab": 0x09,
    "Enter": 0x0D,
    "Shift": 0x10,
    "Control": 0x11,
    "Alt": 0x12,
    "Pause": 0x13,
    "CapsLock": 0x14,
    "Escape": 0x1B,
    " ": 0x20,
    "PageUp": 0x21,
    "PageDown": 0x22,
    "End": 0x23,
    "Home": 0x24,
    "ArrowLeft": 0x25,
    "ArrowUp": 0x26,
    "ArrowRight": 0x27,
    "ArrowDown": 0x28,
    "Insert": 0x2D,
    "Delete": 0x2E,
    "Meta": 0x5B,
    "F1": 0x70,
    "F2": 0x71,
    "F3": 0x72,
    "F4": 0x73,
    "F5": 0x74,
    "F6": 0x75,
    "F7": 0x76,
    "F8": 0x77,
    "F9": 0x78,
    "F10": 0x79,
    "F11": 0x7A,
    "F12": 0x7B,
}


RECT = wintypes.RECT


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
gdi32.GetDIBits.argtypes = [
    wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
    ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int


class CaptureError(RuntimeError):
    pass


class ScreenCapture:
    def __init__(self):
        self.lock = threading.Lock()

    def _rect(self, mode: str):
        if mode == "active":
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                rect = RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    width = rect.right - rect.left
                    height = rect.bottom - rect.top
                    if width > 16 and height > 16:
                        return rect.left, rect.top, width, height
        left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        if width <= 0 or height <= 0:
            raise CaptureError("无法读取 Windows 虚拟桌面尺寸")
        return left, top, width, height

    def capture(self, mode: str):
        left, top, width, height = self._rect(mode)
        with self.lock:
            screen_dc = user32.GetDC(0)
            if not screen_dc:
                raise CaptureError("GetDC 失败")
            mem_dc = gdi32.CreateCompatibleDC(screen_dc)
            bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
            old_obj = None
            try:
                if not mem_dc or not bitmap:
                    raise CaptureError("创建 GDI 缓冲区失败")
                old_obj = gdi32.SelectObject(mem_dc, bitmap)
                ok = gdi32.BitBlt(
                    mem_dc, 0, 0, width, height,
                    screen_dc, left, top, SRCCOPY | CAPTUREBLT,
                )
                if not ok:
                    raise CaptureError("BitBlt 失败")

                bmi = BITMAPINFO()
                bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                bmi.bmiHeader.biWidth = width
                bmi.bmiHeader.biHeight = -height
                bmi.bmiHeader.biPlanes = 1
                bmi.bmiHeader.biBitCount = 32
                bmi.bmiHeader.biCompression = BI_RGB
                buf = ctypes.create_string_buffer(width * height * 4)
                lines = gdi32.GetDIBits(
                    mem_dc, bitmap, 0, height, buf, ctypes.byref(bmi), DIB_RGB_COLORS
                )
                if lines != height:
                    raise CaptureError("GetDIBits 失败")
                return left, top, width, height, buf.raw
            finally:
                if old_obj:
                    gdi32.SelectObject(mem_dc, old_obj)
                if bitmap:
                    gdi32.DeleteObject(bitmap)
                if mem_dc:
                    gdi32.DeleteDC(mem_dc)
                user32.ReleaseDC(0, screen_dc)


def _vk_for_key(key: str):
    if key in VK_SPECIAL:
        return VK_SPECIAL[key]
    if len(key) == 1:
        value = user32.VkKeyScanW(ord(key))
        if value != -1:
            return value & 0xFF
    return None


def key_event(key: str, down: bool):
    vk = _vk_for_key(key)
    if vk is None:
        return
    flags = 0 if down else KEYEVENTF_KEYUP
    user32.keybd_event(vk, 0, flags, 0)


def unicode_text(text: str):
    for ch in text:
        codepoint = ord(ch)
        if codepoint <= 0xFFFF:
            units = [codepoint]
        else:
            codepoint -= 0x10000
            units = [0xD800 + (codepoint >> 10), 0xDC00 + (codepoint & 0x3FF)]
        for unit in units:
            down = INPUT(
                type=INPUT_KEYBOARD,
                ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE, 0, 0),
            )
            up = INPUT(
                type=INPUT_KEYBOARD,
                ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0),
            )
            arr = (INPUT * 2)(down, up)
            user32.SendInput(2, arr, ctypes.sizeof(INPUT))


def set_clipboard_text(text: str):
    encoded = (text + "\0").encode("utf-16-le")
    if not user32.OpenClipboard(None):
        raise RuntimeError("无法打开云电脑剪贴板")
    handle = None
    try:
        if not user32.EmptyClipboard():
            raise RuntimeError("无法清空云电脑剪贴板")
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
        if not handle:
            raise RuntimeError("GlobalAlloc 失败")
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            raise RuntimeError("GlobalLock 失败")
        try:
            ctypes.memmove(ptr, encoded, len(encoded))
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise RuntimeError("SetClipboardData 失败")
        handle = None
    finally:
        user32.CloseClipboard()
        if handle:
            kernel32.GlobalFree(handle)


def paste_text(text: str):
    set_clipboard_text(text)
    key_event("Control", True)
    key_event("v", True)
    key_event("v", False)
    key_event("Control", False)


def mouse_event(payload: dict):
    action = payload.get("action", "")
    x = int(payload.get("x", 0))
    y = int(payload.get("y", 0))
    user32.SetCursorPos(x, y)
    if action == "move":
        return
    button = payload.get("button", 0)
    if action in {"down", "up"}:
        flags = {
            (0, "down"): MOUSEEVENTF_LEFTDOWN,
            (0, "up"): MOUSEEVENTF_LEFTUP,
            (1, "down"): MOUSEEVENTF_MIDDLEDOWN,
            (1, "up"): MOUSEEVENTF_MIDDLEUP,
            (2, "down"): MOUSEEVENTF_RIGHTDOWN,
            (2, "up"): MOUSEEVENTF_RIGHTUP,
        }.get((button, action))
        if flags:
            user32.mouse_event(flags, 0, 0, 0, 0)
    elif action == "wheel":
        delta = int(payload.get("delta", 0))
        if delta:
            user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta, 0)


VIEWER_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>云电脑网页镜像</title>
<style>
:root{font-family:"Microsoft YaHei",system-ui,sans-serif;color:#111827;background:#0b1020}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:#0b1020;color:#e5e7eb}
.toolbar{height:52px;display:flex;align-items:center;gap:12px;padding:8px 14px;background:#111827;border-bottom:1px solid #263248;position:sticky;top:0;z-index:2}
.toolbar strong{margin-right:auto}.toolbar label,.toolbar button{font-size:14px}
button,select{border:1px solid #475569;border-radius:8px;background:#1f2937;color:#f8fafc;padding:7px 10px}
.status{font-size:13px;color:#93c5fd}.stage{height:calc(100vh - 52px);display:grid;place-items:center;overflow:hidden;background:#020617}
canvas{display:block;max-width:100%;max-height:100%;outline:none;cursor:default;image-rendering:auto}
.hint{position:fixed;right:12px;bottom:10px;padding:6px 9px;border-radius:7px;background:rgba(15,23,42,.78);font-size:12px;color:#cbd5e1;pointer-events:none}
</style>
</head>
<body>
<div class="toolbar">
  <strong>云电脑网页镜像</strong>
  <span class="status" id="status">正在连接…</span>
  <label>画面
    <select id="mode"><option value="active">当前窗口</option><option value="screen">完整桌面</option></select>
  </label>
  <label><input type="checkbox" id="control"> 允许控制</label>
  <button id="fullscreen">全屏</button>
</div>
<div class="stage" id="stage"><canvas id="view" tabindex="0"></canvas></div>
<div class="hint">点击画面后可输入；Ctrl+V 可把本机剪贴板文字粘贴到云电脑</div>
<script>
const TOKEN = "__TOKEN__";
const canvas = document.getElementById("view");
const ctx = canvas.getContext("2d", {alpha:false});
const statusEl = document.getElementById("status");
const modeEl = document.getElementById("mode");
const controlEl = document.getElementById("control");
let frame = {left:0,top:0,width:1,height:1};
let running = true;
let failures = 0;
let lastMoveAt = 0;

function endpoint(path){ return path + "?token=" + encodeURIComponent(TOKEN); }

async function inflate(bytes){
  if(!("DecompressionStream" in window)) throw new Error("当前浏览器不支持 DecompressionStream，请使用新版 Chrome/Edge");
  const ds = new DecompressionStream("deflate");
  const stream = new Blob([bytes]).stream().pipeThrough(ds);
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

async function pullFrame(){
  while(running){
    const started = performance.now();
    try{
      const res = await fetch(endpoint("/api/frame") + "&mode=" + encodeURIComponent(modeEl.value), {cache:"no-store"});
      if(!res.ok) throw new Error("HTTP " + res.status);
      const ab = await res.arrayBuffer();
      const dv = new DataView(ab,0,16);
      const width = dv.getInt32(0,true), height = dv.getInt32(4,true);
      const left = dv.getInt32(8,true), top = dv.getInt32(12,true);
      const raw = await inflate(new Uint8Array(ab,16));
      if(raw.length !== width*height*4) throw new Error("画面长度异常");
      const rgba = new Uint8ClampedArray(raw.length);
      for(let i=0;i<raw.length;i+=4){
        rgba[i] = raw[i+2];
        rgba[i+1] = raw[i+1];
        rgba[i+2] = raw[i];
        rgba[i+3] = 255;
      }
      canvas.width = width; canvas.height = height;
      ctx.putImageData(new ImageData(rgba,width,height),0,0);
      frame = {left,top,width,height};
      failures = 0;
      statusEl.textContent = "已连接 · " + width + "×" + height;
    }catch(err){
      failures++;
      statusEl.textContent = "连接异常：" + err.message;
      await new Promise(r=>setTimeout(r,Math.min(2000,250*failures)));
    }
    const elapsed = performance.now()-started;
    const wait = Math.max(0, 90-elapsed);
    if(wait) await new Promise(r=>setTimeout(r,wait));
  }
}

function canvasPoint(ev){
  const r = canvas.getBoundingClientRect();
  const x = Math.max(0,Math.min(frame.width-1,(ev.clientX-r.left)*frame.width/r.width));
  const y = Math.max(0,Math.min(frame.height-1,(ev.clientY-r.top)*frame.height/r.height));
  return {x:Math.round(frame.left+x), y:Math.round(frame.top+y)};
}
function send(payload){
  if(!controlEl.checked) return;
  fetch(endpoint("/api/input"),{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify(payload),
    keepalive:true
  }).catch(()=>{});
}
canvas.addEventListener("mousemove", ev=>{
  if(!controlEl.checked) return;
  const now=performance.now(); if(now-lastMoveAt<25) return; lastMoveAt=now;
  const p=canvasPoint(ev); send({type:"mouse",action:"move",...p});
});
canvas.addEventListener("mousedown", ev=>{
  if(!controlEl.checked) return;
  ev.preventDefault(); canvas.focus();
  const p=canvasPoint(ev); send({type:"mouse",action:"down",button:ev.button,...p});
});
canvas.addEventListener("mouseup", ev=>{
  if(!controlEl.checked) return;
  ev.preventDefault(); const p=canvasPoint(ev); send({type:"mouse",action:"up",button:ev.button,...p});
});
canvas.addEventListener("contextmenu", ev=>ev.preventDefault());
canvas.addEventListener("wheel", ev=>{
  if(!controlEl.checked) return;
  ev.preventDefault(); const p=canvasPoint(ev);
  const delta = ev.deltaY < 0 ? 120 : -120;
  send({type:"mouse",action:"wheel",delta,...p});
},{passive:false});

canvas.addEventListener("keydown", ev=>{
  if(!controlEl.checked) return;
  if((ev.ctrlKey||ev.metaKey) && ev.key.toLowerCase()==="v") return;
  ev.preventDefault();
  send({type:"key",action:"down",key:ev.key});
});
canvas.addEventListener("keyup", ev=>{
  if(!controlEl.checked) return;
  if((ev.ctrlKey||ev.metaKey) && ev.key.toLowerCase()==="v") return;
  ev.preventDefault();
  send({type:"key",action:"up",key:ev.key});
});
canvas.addEventListener("paste", ev=>{
  if(!controlEl.checked) return;
  const text = ev.clipboardData && ev.clipboardData.getData("text");
  if(text){ ev.preventDefault(); send({type:"paste",text}); }
});
document.addEventListener("paste", ev=>{
  if(document.activeElement===canvas) return;
  if(!controlEl.checked) return;
  const text = ev.clipboardData && ev.clipboardData.getData("text");
  if(text){ ev.preventDefault(); send({type:"paste",text}); }
});
document.getElementById("fullscreen").addEventListener("click",()=>document.getElementById("stage").requestFullscreen());
controlEl.addEventListener("change",()=>{ if(controlEl.checked) canvas.focus(); });
pullFrame();
</script>
</body>
</html>
"""


class MirrorHandler(BaseHTTPRequestHandler):
    server_version = "ChenCloudMirror/0.1"

    def log_message(self, fmt, *args):
        if self.server.verbose:
            super().log_message(fmt, *args)

    def _query(self):
        return urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)

    def _authorized(self):
        token = self._query().get("token", [""])[0]
        return secrets.compare_digest(token, self.server.token)

    def _send(self, status, body=b"", content_type="text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/health":
            self._send(200, b'{"ok":true}', "application/json")
            return
        if not self._authorized():
            self._send(403, "访问令牌无效。请使用云电脑启动窗口打印出的完整地址。".encode("utf-8"))
            return
        if parsed.path == "/":
            html = VIEWER_HTML.replace("__TOKEN__", self.server.token)
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/frame":
            mode = self._query().get("mode", ["active"])[0]
            mode = "screen" if mode == "screen" else "active"
            try:
                left, top, width, height, raw = self.server.capture.capture(mode)
                payload = struct.pack("<iiii", width, height, left, top) + zlib.compress(raw, 1)
                self._send(200, payload, "application/octet-stream")
            except Exception as exc:
                self._send(500, str(exc).encode("utf-8", "replace"))
            return
        self._send(404, b"Not found")

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != "/api/input":
            self._send(404, b"Not found")
            return
        if not self._authorized():
            self._send(403, b"Forbidden")
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 1024 * 1024)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            typ = payload.get("type")
            if typ == "mouse":
                mouse_event(payload)
            elif typ == "key":
                key_event(str(payload.get("key", "")), payload.get("action") == "down")
            elif typ == "paste":
                text = str(payload.get("text", ""))[:200000]
                paste_text(text)
            else:
                raise ValueError("未知输入类型")
            self._send(204)
        except Exception as exc:
            self._send(400, str(exc).encode("utf-8", "replace"))


class MirrorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, token, verbose=False):
        super().__init__(address, MirrorHandler)
        self.token = token
        self.verbose = verbose
        self.capture = ScreenCapture()


def local_ipv4_candidates():
    found = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = item[4][0]
            if not ip.startswith("127."):
                found.add(ip)
    except OSError:
        pass
    return sorted(found)


def main():
    parser = argparse.ArgumentParser(description="晨的小助手：云电脑浏览器镜像代理（纯局域网/零公网依赖）")
    parser.add_argument("--bind", default="127.0.0.1", help="监听地址；需要从本机访问时通常使用 0.0.0.0")
    parser.add_argument("--port", type=int, default=18764)
    parser.add_argument("--token", default="", help="访问令牌；留空则每次启动随机生成")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    token = args.token.strip() or secrets.token_urlsafe(18)
    server = MirrorServer((args.bind, args.port), token=token, verbose=args.verbose)

    print("=" * 72)
    print("晨的小助手 · 云电脑网页镜像代理")
    print(f"监听：{args.bind}:{args.port}")
    print("本机浏览器请访问：")
    ips = local_ipv4_candidates()
    if args.bind in {"0.0.0.0", "::"} and ips:
        for ip in ips:
            print(f"  http://{ip}:{args.port}/?token={urllib.parse.quote(token)}")
    else:
        host = "127.0.0.1" if args.bind == "127.0.0.1" else args.bind
        print(f"  http://{host}:{args.port}/?token={urllib.parse.quote(token)}")
    print()
    print("如果本机无法打开上面的地址，请先在本机 PowerShell 测试：")
    print(f"  Test-NetConnection <云电脑IP> -Port {args.port}")
    print("按 Ctrl+C 停止。")
    print("=" * 72)

    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
