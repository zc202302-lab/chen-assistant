"""CLI and batch orchestration. Workbook, CDP and member operation are separate."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from member_models import AutomationError, UncertainSubmission, MemberTask
from member_workbook import read_member_tasks_xlsx, empty_relay_workbook, EMPTY_RELAY_MARKER
from member_browser import Cdp, SearchRefreshGuard, _find_targets, _frame_ids, _evaluate
from member_page import _FIND_SEARCH_INPUT, _GROUP_IDENTITIES
from member_flow import MemberAdder
from relay_store import capture_relay, clear_if_unchanged

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
DEFAULT_BRIDGE = Path(r"Y:\ChenBridge")

@dataclass
class Agent:
    bridge: Path = DEFAULT_BRIDGE
    port: int = 9222

    def prepare(self):
        for folder in ("processing", "processed", "results", "errors", "logs"):
            (self.bridge / folder).mkdir(parents=True, exist_ok=True)

    def process(self, source: Path) -> Path | None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            payload = capture_relay(source)
        except OSError:
            return None  # Excel/sync may hold the relay; try later without consuming it.
        batch_id = hashlib.sha256(payload).hexdigest()[:16]
        if any((self.bridge / "results").glob(f"号码加集团_结果_*_{batch_id}.json")):
            print("此批已有结果，已跳过；请查看results，失败或不确定批次不会自动重试。", flush=True)
            return None
        # The fixed relay file remains at its original path throughout processing.
        claimed = self.bridge / "processing" / f"号码加集团_{stamp}_{uuid.uuid4().hex[:8]}.xlsx"
        claimed.write_bytes(payload)
        result_path = self.bridge / "results" / f"号码加集团_结果_{stamp}_{batch_id}.json"
        try:
            tasks = read_member_tasks_xlsx(claimed, allow_empty=True)
            if not tasks:
                claimed.unlink()
                return None
            adder = MemberAdder(self.port)
            outcomes = []
            stop_reason = ""
            for index, task in enumerate(tasks):
                if stop_reason:
                    outcomes.append({"row": task.row_number, "service_number": task.service_number, "group_search": task.group_search, "status": "未执行", "detail": stop_reason})
                    continue
                try:
                    status, detail = adder.add_one(task)
                    outcomes.append({"row": task.row_number, "service_number": task.service_number, "group_search": task.group_search, "status": status, "detail": detail})
                except UncertainSubmission as exc:
                    outcomes.append({"row": task.row_number, "service_number": task.service_number, "group_search": task.group_search, "status": "结果待人工核对", "detail": str(exc)})
                    stop_reason = "前一行提交结果不确定，已暂停本批剩余号码"
                except Exception as exc:
                    outcomes.append({"row": task.row_number, "service_number": task.service_number, "group_search": task.group_search, "status": "失败，已暂停", "detail": str(exc)})
                    stop_reason = f"第 {task.row_number} 行执行失败，已暂停本批剩余号码"
            result = {"version": 1, "batch_id": batch_id, "source_file": "号码加集团.xlsx", "finished_at": datetime.now(timezone.utc).isoformat(), "count": len(tasks), "results": outcomes}
            archive_dir = self.bridge / "processed"
        except Exception as exc:
            result = {"version": 1, "batch_id": batch_id, "source_file": "号码加集团.xlsx", "finished_at": datetime.now(timezone.utc).isoformat(), "count": 0, "error": str(exc), "results": []}
            archive_dir = self.bridge / "errors"
        temp = result_path.with_suffix(result_path.suffix + ".tmp")
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(result_path)
        destination = archive_dir / claimed.name
        try:
            claimed.replace(destination)
        except OSError:
            # Result file remains authoritative if cloud-drive sync temporarily locks the archive move.
            pass
        # Do not clear a newer batch written while this batch was being processed.
        try:
            cleared = clear_if_unchanged(source, payload, empty_relay_workbook())
        except OSError:
            cleared = False
        if cleared:
            print("本批处理结束，中转文件已清空并保留；结果：" + str(result_path), flush=True)
        else:
            print("结果已保存；中转文件被修改或占用，已保留其内容：" + str(result_path), flush=True)
        return result_path

    def run(self, once: bool = False):
        # Check the browser before claiming a workbook from shared storage.
        self.check_browser()
        self.prepare()
        print(f"助手已启动，等待任务：{self.bridge / '号码加集团.xlsx'}", flush=True)
        while True:
            # Only between batches; updater replaces files after this process exits.
            if getattr(sys, "frozen", False) and __import__("os").environ.get("CHEN_OFFLINE_UPDATE") == "1":
                from offline_update import pending
                if pending(self.bridge, Path(sys.executable).parent):
                    print("发现新版，本批已结束，交由离线更新器安装。", flush=True)
                    sys.exit(75)
            source = self.bridge / "号码加集团.xlsx"
            if source.exists():
                self.check_browser()
                self.process(source)
                if once:
                    return
            elif once:
                return
            time.sleep(1.0)

    def diagnose_browser(self):
        main, _ = _find_targets(self.port)
        cdp = Cdp(main["webSocketDebuggerUrl"])
        results = []
        try:
            cdp.call("Page.enable")
            tree = cdp.call("Page.getFrameTree").get("frameTree", {})
            for frame_id in _frame_ids(tree):
                try:
                    world = cdp.call("Page.createIsolatedWorld", {"frameId": frame_id, "worldName": "chen-member-agent"})
                    result = _evaluate(cdp, _FIND_SEARCH_INPUT, int(world["executionContextId"]))
                    identities = _evaluate(cdp, _GROUP_IDENTITIES, int(world["executionContextId"]))
                    results.append({"frame": frame_id, "search": result, "group_identities": identities})
                except Exception as exc:
                    results.append({"frame": frame_id, "error": str(exc)})
        finally:
            cdp.close()
        print(json.dumps({"read_only": True, "frames": results}, ensure_ascii=False, indent=2), flush=True)

    def check_browser(self):
        main, _ = _find_targets(self.port)
        result = MemberAdder(self.port)._with_context(main, _FIND_SEARCH_INPUT)
        if not isinstance(result, dict) or not result.get("ok"):
            raise AutomationError("未识别业务搜索控件：" + str((result or {}).get("reason") or "页面框架无法读取；请运行 diagnose_browser.cmd"))
        return main


def main():
    parser = argparse.ArgumentParser(description="云电脑助手：批量添加集团成员")
    parser.add_argument("--bridge", type=Path, default=DEFAULT_BRIDGE)
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--once", action="store_true", help="只处理当前号码加集团.xlsx 后退出")
    parser.add_argument("--check-file", type=Path, help="只校验 Excel 两列，不连接业务系统")
    parser.add_argument("--check-browser", action="store_true", help="只检查浏览器连接和业务搜索框，不提交成员")
    parser.add_argument("--diagnose-browser", action="store_true", help="只读诊断页面框架和搜索控件")
    args = parser.parse_args()
    if args.diagnose_browser:
        Agent(args.bridge, args.port).diagnose_browser()
        return
    if args.check_file:
        tasks = read_member_tasks_xlsx(args.check_file)
        print(json.dumps({"ok": True, "rows": len(tasks), "first_row": tasks[0].row_number}, ensure_ascii=False))
        return
    if args.check_browser:
        Agent(args.bridge, args.port).check_browser()
        print("浏览器连接正常，业务搜索框已找到。此检查未提交成员。", flush=True)
        return
    Agent(args.bridge, args.port).run(args.once)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        print(f"助手未能继续：{exc}", file=sys.stderr, flush=True)
        print("请确认共享目录已连接；用调试快捷方式打开浏览器，并重新登录业务系统后再启动。", file=sys.stderr, flush=True)
        sys.exit(1)
