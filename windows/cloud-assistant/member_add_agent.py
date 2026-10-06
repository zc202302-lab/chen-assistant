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
from task_journal import BatchJournal, batch_lock, atomic_json

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
DEFAULT_BRIDGE = Path(r"Y:\ChenBridge")

@dataclass
class Agent:
    bridge: Path = DEFAULT_BRIDGE
    port: int = 9222
    relay_notice_at: float = 0.0

    def prepare(self):
        for folder in ("processing", "processed", "results", "errors", "logs", "journals"):
            (self.bridge / folder).mkdir(parents=True, exist_ok=True)

    def process(self, source: Path) -> Path | None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            payload = capture_relay(source)
        except OSError:
            # Excel/sync may hold the relay. Explain the wait without flooding logs.
            now = time.monotonic()
            if not self.relay_notice_at or now - self.relay_notice_at >= 10:
                print("云电脑暂时无法读取中转表；请确认共享目录可用，并保存、关闭 Excel。助手会继续等待，文件内容已保留。", flush=True)
                self.relay_notice_at = now
            return None
        batch_id = hashlib.sha256(payload).hexdigest()[:16]
        if any((self.bridge / "results").glob(f"号码加集团_结果_*_{batch_id}.json")):
            print("此批已有结果，已跳过；请查看results，失败或不确定批次不会自动重试。", flush=True)
            return None
        try:
            with batch_lock(self.bridge / "journals", payload) as journal_path:
                return self._process_claimed(source, payload, stamp, batch_id, journal_path)
        except OSError:
            print("任务被占用或记录未能保存；中转内容已保留，请检查共享目录后重启。", flush=True)
            return None

    def _process_claimed(self, source, payload, stamp, batch_id, journal_path):
        # The fixed relay file remains at its original path throughout processing.
        claimed = self.bridge / "processing" / f"号码加集团_{stamp}_{uuid.uuid4().hex[:8]}.xlsx"
        claimed.write_bytes(payload)
        result_path = self.bridge / "results" / f"号码加集团_结果_{stamp}_{batch_id}.json"
        try:
            tasks = read_member_tasks_xlsx(claimed, allow_empty=True)
        except Exception as exc:
            result = {"version": 1, "batch_id": batch_id, "source_file": "号码加集团.xlsx", "finished_at": datetime.now(timezone.utc).isoformat(), "count": 0, "error": str(exc), "results": []}
            archive_dir = self.bridge / "errors"
        else:
            if not tasks:
                claimed.unlink()
                return None
            journal = BatchJournal(journal_path, payload, tasks)
            if journal.recovered:
                outcomes = journal.recovered_outcomes()
            else:
                adder = MemberAdder(self.port)
                stop_reason = ""
                for index, task in enumerate(tasks):
                    if stop_reason:
                        journal.finish(index, "未执行", stop_reason)
                        continue
                    journal.begin(index)
                    try:
                        status, detail = adder.add_one(task)
                    except UncertainSubmission as exc:
                        status, detail = "结果待人工核对", str(exc)
                        stop_reason = "前一行提交结果不确定，已暂停本批剩余号码"
                    except Exception as exc:
                        status, detail = "失败，已暂停", str(exc)
                        stop_reason = f"第 {task.row_number} 行执行失败，已暂停本批剩余号码"
                    journal.finish(index, status, detail)
                outcomes = journal.data['rows']
            result = {"version": 1, "batch_id": batch_id, "source_file": "号码加集团.xlsx", "finished_at": datetime.now(timezone.utc).isoformat(), "count": len(tasks), "results": outcomes}
            archive_dir = self.bridge / "processed"
        atomic_json(result_path, result)
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
    parser.add_argument("--self-check", action="store_true", help="只验证程序导入，不连接业务系统")
    args = parser.parse_args()
    if args.self_check:
        print("member-agent self-check ok", flush=True)
        return
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
        print("请在云电脑检查共享目录映射；浏览器控件未识别时运行 diagnose_browser.cmd 做只读诊断。", file=sys.stderr, flush=True)
        sys.exit(1)
