from __future__ import annotations

import argparse
import json
from pathlib import Path
import os
import struct
import time
import zlib

from cloud_mirror_agent import ScreenCapture, key_event, mouse_event, paste_text


def atomic_write(path: Path, data: bytes):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def process_commands(command_dir: Path):
    for path in sorted(command_dir.glob("*.json"))[:100]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            typ = payload.get("type")
            if typ == "mouse":
                mouse_event(payload)
            elif typ == "key":
                key_event(str(payload.get("key", "")), payload.get("action") == "down")
            elif typ == "paste":
                paste_text(str(payload.get("text", ""))[:200000])
        except Exception:
            pass
        finally:
            try:
                path.unlink()
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description="晨的小助手：共享文件夹云电脑镜像端")
    parser.add_argument("--shared-dir", required=True, help="云电脑可访问的共享文件夹路径")
    parser.add_argument("--mode", choices=["active", "screen"], default="active")
    parser.add_argument("--fps", type=float, default=6.0)
    args = parser.parse_args()

    root = Path(args.shared_dir)
    command_dir = root / "commands"
    root.mkdir(parents=True, exist_ok=True)
    command_dir.mkdir(parents=True, exist_ok=True)
    capture = ScreenCapture()

    fps = min(12.0, max(1.0, args.fps))
    interval = 1.0 / fps
    frame_path = root / "frame.bin"
    status_path = root / "cloud-status.json"

    print("=" * 68)
    print("晨的小助手 · 云电脑镜像端（共享文件夹模式）")
    print(f"共享目录：{root}")
    print(f"画面模式：{args.mode}；目标帧率：{fps:g} FPS")
    print("无需公网、无需云电脑监听端口。按 Ctrl+C 停止。")
    print("=" * 68)

    last_status = 0.0
    try:
        while True:
            started = time.perf_counter()
            process_commands(command_dir)
            try:
                left, top, width, height, raw = capture.capture(args.mode)
                payload = struct.pack("<iiii", width, height, left, top) + zlib.compress(raw, 1)
                atomic_write(frame_path, payload)
                now = time.time()
                if now - last_status > 1:
                    atomic_write(
                        status_path,
                        json.dumps({
                            "ok": True,
                            "time": now,
                            "width": width,
                            "height": height,
                            "left": left,
                            "top": top,
                            "mode": args.mode,
                        }, ensure_ascii=False).encode("utf-8"),
                    )
                    last_status = now
            except Exception as exc:
                atomic_write(
                    status_path,
                    json.dumps({"ok": False, "time": time.time(), "error": str(exc)}, ensure_ascii=False).encode("utf-8"),
                )
                time.sleep(0.5)

            process_commands(command_dir)
            elapsed = time.perf_counter() - started
            if elapsed < interval:
                time.sleep(interval - elapsed)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
