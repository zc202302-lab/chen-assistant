from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import time
import urllib.parse


VIEWER = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>云电脑网页镜像</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#020617;color:#e5e7eb;font-family:"Microsoft YaHei",system-ui,sans-serif}
header{height:52px;display:flex;align-items:center;gap:14px;padding:8px 14px;background:#111827;border-bottom:1px solid #334155}
header strong{margin-right:auto}.status{font-size:13px;color:#93c5fd}
button{background:#1f2937;color:white;border:1px solid #475569;border-radius:8px;padding:7px 10px}
.stage{height:calc(100vh - 52px);display:grid;place-items:center;overflow:hidden}
canvas{display:block;max-width:100%;max-height:100%;outline:none}
.tip{position:fixed;right:10px;bottom:8px;background:rgba(15,23,42,.8);padding:6px 9px;border-radius:7px;font-size:12px;color:#cbd5e1}
</style>
</head>
<body>
<header><strong>云电脑网页镜像</strong><span class="status" id="s">等待云电脑画面…</span><label><input id="ctl" type="checkbox"> 允许控制</label><button id="fs">全屏</button></header>
<div class="stage" id="stage"><canvas id="v" tabindex="0"></canvas></div>
<div class="tip">共享文件夹桥接 · 云电脑无需公网；点击画面后可操作，Ctrl+V 可粘贴文字</div>
<script>
const canvas=document.getElementById("v"),ctx=canvas.getContext("2d",{alpha:false}),s=document.getElementById("s"),ctl=document.getElementById("ctl");
let frame={left:0,top:0,width:1,height:1},lastMove=0,fail=0;
async function inflate(bytes){const ds=new DecompressionStream("deflate");return new Uint8Array(await new Response(new Blob([bytes]).stream().pipeThrough(ds)).arrayBuffer())}
async function loop(){for(;;){const st=performance.now();try{const r=await fetch("/frame?x="+Date.now(),{cache:"no-store"});if(!r.ok)throw new Error("HTTP "+r.status);const ab=await r.arrayBuffer(),dv=new DataView(ab,0,16);const w=dv.getInt32(0,true),h=dv.getInt32(4,true),left=dv.getInt32(8,true),top=dv.getInt32(12,true);const raw=await inflate(new Uint8Array(ab,16));const rgba=new Uint8ClampedArray(raw.length);for(let i=0;i<raw.length;i+=4){rgba[i]=raw[i+2];rgba[i+1]=raw[i+1];rgba[i+2]=raw[i];rgba[i+3]=255}canvas.width=w;canvas.height=h;ctx.putImageData(new ImageData(rgba,w,h),0,0);frame={left,top,width:w,height:h};s.textContent="已连接 · "+w+"×"+h;fail=0}catch(e){fail++;s.textContent="等待画面："+e.message;await new Promise(r=>setTimeout(r,Math.min(1500,200*fail)))}const wait=Math.max(0,120-(performance.now()-st));if(wait)await new Promise(r=>setTimeout(r,wait))}}
function p(ev){const r=canvas.getBoundingClientRect();return{x:Math.round(frame.left+Math.max(0,Math.min(frame.width-1,(ev.clientX-r.left)*frame.width/r.width))),y:Math.round(frame.top+Math.max(0,Math.min(frame.height-1,(ev.clientY-r.top)*frame.height/r.height)))}}
function send(x){if(!ctl.checked)return;fetch("/input",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(x),keepalive:true}).catch(()=>{})}
canvas.onmousemove=e=>{if(!ctl.checked)return;const n=performance.now();if(n-lastMove<30)return;lastMove=n;send({type:"mouse",action:"move",...p(e)})};
canvas.onmousedown=e=>{if(!ctl.checked)return;e.preventDefault();canvas.focus();send({type:"mouse",action:"down",button:e.button,...p(e)})};
canvas.onmouseup=e=>{if(!ctl.checked)return;e.preventDefault();send({type:"mouse",action:"up",button:e.button,...p(e)})};
canvas.oncontextmenu=e=>e.preventDefault();
canvas.addEventListener("wheel",e=>{if(!ctl.checked)return;e.preventDefault();send({type:"mouse",action:"wheel",delta:e.deltaY<0?120:-120,...p(e)})},{passive:false});
canvas.onkeydown=e=>{if(!ctl.checked)return;if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="v")return;e.preventDefault();send({type:"key",action:"down",key:e.key})};
canvas.onkeyup=e=>{if(!ctl.checked)return;if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="v")return;e.preventDefault();send({type:"key",action:"up",key:e.key})};
document.addEventListener("paste",e=>{if(!ctl.checked)return;const t=e.clipboardData&&e.clipboardData.getData("text");if(t){e.preventDefault();send({type:"paste",text:t})}});
ctl.onchange=()=>{if(ctl.checked)canvas.focus()};document.getElementById("fs").onclick=()=>document.getElementById("stage").requestFullscreen();loop();
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_bytes(self, status, body=b"", content_type="application/octet-stream"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/":
            self.send_bytes(200, VIEWER.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/frame":
            try:
                data = self.server.frame_path.read_bytes()
                if len(data) < 16:
                    raise OSError("画面文件尚未就绪")
                self.send_bytes(200, data)
            except OSError as exc:
                self.send_bytes(503, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
            return
        if path == "/status":
            try:
                self.send_bytes(200, self.server.status_path.read_bytes(), "application/json")
            except OSError:
                self.send_bytes(503, b'{"ok":false}')
            return
        self.send_bytes(404, b"Not found", "text/plain")

    def do_POST(self):
        if urllib.parse.urlsplit(self.path).path != "/input":
            self.send_bytes(404, b"Not found", "text/plain")
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 1024 * 1024)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            payload["created_at"] = time.time()
            name = f"{time.time_ns()}-{secrets.token_hex(4)}.json"
            tmp = self.server.command_dir / (name + ".tmp")
            final = self.server.command_dir / name
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(final)
            self.send_bytes(204)
        except Exception as exc:
            self.send_bytes(400, str(exc).encode("utf-8"), "text/plain; charset=utf-8")


class Server(ThreadingHTTPServer):
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser(description="晨的小助手：本机浏览器镜像桥")
    ap.add_argument("--shared-dir", required=True, help="本机可访问的同一个共享文件夹")
    ap.add_argument("--port", type=int, default=18765)
    args = ap.parse_args()

    root = Path(args.shared_dir)
    command_dir = root / "commands"
    command_dir.mkdir(parents=True, exist_ok=True)

    server = Server(("127.0.0.1", args.port), Handler)
    server.frame_path = root / "frame.bin"
    server.status_path = root / "cloud-status.json"
    server.command_dir = command_dir

    print("=" * 68)
    print("晨的小助手 · 本机浏览器镜像桥")
    print(f"共享目录：{root}")
    print(f"浏览器打开：http://127.0.0.1:{args.port}/")
    print("这个地址只监听本机，不对外网开放。按 Ctrl+C 停止。")
    print("=" * 68)
    try:
        server.serve_forever(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
