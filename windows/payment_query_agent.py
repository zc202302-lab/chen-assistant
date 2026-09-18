from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    import websocket
except ImportError:  # pragma: no cover - installer supplies it
    websocket = None


TARGET_MARKER = "10.19.89.56/esop/"
DEFAULT_BRIDGE = Path(r"Y:\ChenBridge")
MONEY_RE = re.compile(r"(?<!\d)(-?\d{1,7}(?:\.\d{1,2})?)(?!\d)")


def next_five_band(value: float) -> int:
    """Business rule: 60..64 -> 65 and 65..69 -> 70."""
    if not math.isfinite(value) or value < 0:
        raise ValueError("金额不是有效的非负数字")
    return (math.floor(value / 5) + 1) * 5


def _label_money(text: str, label: str) -> float | None:
    match = re.search(re.escape(label) + r"\s*[:：]?\s*(-?\d+(?:\.\d{1,2})?)", text)
    return float(match.group(1)) if match else None


def calculate_amount(page_text: str) -> tuple[int, dict]:
    compact = re.sub(r"[\t\u00a0 ]+", " ", page_text)
    product_match = re.search(r"产品类型\s*[:：]?\s*([^\r\n]+)", compact)
    product_type = product_match.group(1).strip() if product_match else ""

    if "后付费" in product_type:
        receivable = _label_money(compact, "应收金额")
        unbilled = _label_money(compact, "未出账话费")
        if receivable is None or unbilled is None:
            raise ValueError("没有同时读取到应收金额和未出账话费")
        raw = receivable if abs(receivable) > 0.000001 else unbilled
        rule = "后付费：应收金额非零优先，否则取未出账话费"
    elif "预付费" in product_type:
        marker = compact.find("应结账单")
        if marker < 0:
            raise ValueError("没有找到应结账单区域")
        section = compact[marker:]
        candidates = [
            float(x) for x in MONEY_RE.findall(section)
            if len(x.replace(".", "").replace("-", "")) <= 7
        ]
        if not candidates:
            raise ValueError("应结账单区域没有可用金额")
        raw = max(candidates)
        rule = "预付费：取应结账单区域最大金额"
    else:
        raise ValueError(f"无法识别产品类型：{product_type or '空'}")

    amount = next_five_band(raw)
    return amount, {
        "product_type": product_type,
        "raw_amount": raw,
        "rule": rule,
        "rounding": "进入下一个5元档",
    }


class Cdp:
    def __init__(self, ws_url: str):
        if websocket is None:
            raise RuntimeError("缺少 websocket-client，请重新运行安装程序")
        self.ws = websocket.create_connection(ws_url, timeout=8, suppress_origin=True)
        self.seq = 0

    def call(self, method: str, params: dict | None = None) -> dict:
        self.seq += 1
        call_id = self.seq
        self.ws.send(json.dumps({"id": call_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") != call_id:
                continue
            if "error" in message:
                raise RuntimeError(f"CDP {method} 失败：{message['error']}")
            return message.get("result", {})

    def close(self):
        self.ws.close()


def _json_url(url: str):
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def find_business_target(port: int) -> dict:
    targets = _json_url(f"http://127.0.0.1:{port}/json/list")
    matches = [x for x in targets if x.get("type") == "page" and TARGET_MARKER in x.get("url", "")]
    if not matches:
        raise RuntimeError("未找到业务查询窗口；请用调试快捷方式启动浏览器并保持查询窗口打开")
    return matches[0]


def _frame_ids(tree: dict) -> list[str]:
    result = []

    def walk(node):
        frame_id = node.get("frame", {}).get("id")
        if frame_id:
            result.append(frame_id)
        for child in node.get("childFrames") or []:
            walk(child)

    walk(tree)
    return result


QUERY_SCRIPT = r"""
(async queryValue => {
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const text = el => (el?.innerText || el?.textContent || '').replace(/\s+/g, ' ').trim();
  const compact = value => String(value || '').replace(/\s+/g, '');
  const controls = [...document.querySelectorAll('input,button,a')].filter(visible);
  const radios = controls.filter(el => el.tagName === 'INPUT' && el.type === 'radio');
  const radioCaption = radio => {
    if (radio.labels?.length) return text(radio.labels[0]);
    let value = '';
    let node = radio.nextSibling;
    while (node && value.length < 40) {
      if (node.nodeType === Node.ELEMENT_NODE && node.matches?.('input[type="radio"]')) break;
      value += ` ${node.textContent || ''}`;
      node = node.nextSibling;
    }
    return value.replace(/\s+/g, ' ').trim();
  };
  const accountRadio = document.getElementById('chargeTypeByAcct')
    || radios.find(el => /按(帐|账)户查询/.test(compact(radioCaption(el))))
    || radios[1];
  // The operator chooses the query mode. Never change either radio here.
  if (!accountRadio || !accountRadio.checked) {
    return {acted:false, accountMode:false};
  }
  const inputs = controls.filter(el => el.tagName === 'INPUT' && !['hidden','button','submit','radio','checkbox'].includes(el.type));
  // Visual position is authoritative on this legacy page: its DOM order does
  // not match the screen layout. Pick the nearest editable field on the same
  // horizontal row and to the right of the account-query radio.
  const radioRect = accountRadio.getBoundingClientRect();
  const radioY = (radioRect.top + radioRect.bottom) / 2;
  const input = document.querySelector('input[name="telnumber"]') || inputs.map(el => {
    const rect = el.getBoundingClientRect();
    return {el, rect, dy: Math.abs((rect.top + rect.bottom) / 2 - radioY)};
  }).filter(x => x.rect.left > radioRect.right && x.dy <= 18)
    .sort((a, b) => a.dy - b.dy || a.rect.left - b.rect.left)[0]?.el;
  if (!input) return {acted:false};
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(input, queryValue);
  // The legacy form reads the current value when "确定" is clicked. Do not
  // emit input/change events because the page binds unrelated mode switching.
  if (!accountRadio.checked) {
    return {acted:false, filled:true, accountMode:false};
  }
  const inputRect = input.getBoundingClientRect();
  const inputY = (inputRect.top + inputRect.bottom) / 2;
  const action = controls.map(el => {
    const rect = el.getBoundingClientRect();
    return {el, rect, dy: Math.abs((rect.top + rect.bottom) / 2 - inputY)};
  }).filter(x => x.rect.left > inputRect.right && x.dy <= 18
    && /^(确定|查询)$/.test(compact(x.el.value || text(x.el))))
    .sort((a, b) => a.dy - b.dy || a.rect.left - b.rect.left)[0]?.el;
  if (!action) return {acted:false, filled:true};
  action.click();
  return {acted:true};
})(%s)
"""


INSPECT_SCRIPT = r"""
(async queryValue => {
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const text = el => (el?.innerText || el?.textContent || '').replace(/\s+/g, ' ').trim();
  const compact = value => String(value || '').replace(/\s+/g, '');
  const controls = [...document.querySelectorAll('input,button,a')].filter(visible);
  const radios = controls.filter(el => el.tagName === 'INPUT' && el.type === 'radio');
  const radioCaption = radio => {
    if (radio.labels?.length) return text(radio.labels[0]);
    let value = '';
    let node = radio.nextSibling;
    while (node && value.length < 40) {
      if (node.nodeType === Node.ELEMENT_NODE && node.matches?.('input[type="radio"]')) break;
      value += ` ${node.textContent || ''}`;
      node = node.nextSibling;
    }
    return value.replace(/\s+/g, ' ').trim();
  };
  const accountRadio = document.getElementById('chargeTypeByAcct')
    || radios.find(el => /按(帐|账)户查询/.test(compact(radioCaption(el))))
    || radios[1];
  if (!accountRadio) return {found:false};
  const selected = () => radios.map((el, index) => ({
    index, caption: radioCaption(el), checked: !!el.checked,
    id: el.id || '', name: el.name || '', value: el.value || ''
  }));
  const before = selected();
  const inputs = controls.filter(el => el.tagName === 'INPUT' && !['hidden','button','submit','radio','checkbox'].includes(el.type));
  const radioRect = accountRadio.getBoundingClientRect();
  const radioY = (radioRect.top + radioRect.bottom) / 2;
  const input = document.querySelector('input[name="telnumber"]') || inputs.map(el => {
    const rect = el.getBoundingClientRect();
    return {el, rect, dy: Math.abs((rect.top + rect.bottom) / 2 - radioY)};
  }).filter(x => x.rect.left > radioRect.right && x.dy <= 18)
    .sort((a, b) => a.dy - b.dy || a.rect.left - b.rect.left)[0]?.el;
  if (!input) return {found:false, before};
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(input, queryValue);
  await new Promise(resolve => setTimeout(resolve, 1000));
  return {
    found:true,
    before,
    after:selected(),
    input:{
      id:input.id || '', name:input.name || '', type:input.type || '', value:input.value || '',
      left:Math.round(input.getBoundingClientRect().left),
      top:Math.round(input.getBoundingClientRect().top)
    }
  };
})(%s)
"""


def frame_contexts(cdp: Cdp) -> list[int]:
    tree = cdp.call("Page.getFrameTree").get("frameTree", {})
    contexts = []
    for frame_id in _frame_ids(tree):
        try:
            world = cdp.call("Page.createIsolatedWorld", {"frameId": frame_id, "worldName": "chen-payment-agent"})
            contexts.append(int(world["executionContextId"]))
        except Exception:
            continue
    return contexts


def evaluate(cdp: Cdp, context_id: int, expression: str):
    result = cdp.call("Runtime.evaluate", {
        "expression": expression,
        "contextId": context_id,
        "returnByValue": True,
        "awaitPromise": True,
    })
    if result.get("exceptionDetails"):
        raise RuntimeError("页面脚本执行失败")
    return result.get("result", {}).get("value")


def run_query(query_value: str, port: int) -> tuple[int, dict]:
    target = find_business_target(port)
    cdp = Cdp(target["webSocketDebuggerUrl"])
    try:
        cdp.call("Page.enable")
        contexts = frame_contexts(cdp)
        acted = False
        account_mode_invalid = False
        for context_id in contexts:
            result = evaluate(cdp, context_id, QUERY_SCRIPT % json.dumps(query_value, ensure_ascii=False))
            account_mode_invalid = account_mode_invalid or bool(
                result and result.get("accountMode") is False
            )
            acted = acted or bool(result and result.get("acted"))
            if acted:
                break
        if not acted:
            if account_mode_invalid:
                raise RuntimeError("当前未选中“按账户查询”；程序没有切换查询方式，也没有提交")
            raise RuntimeError("没有找到业务系统的账户查询输入框或确定按钮")

        deadline = time.time() + 18
        last_error = "查询结果尚未出现"
        while time.time() < deadline:
            time.sleep(0.8)
            texts = []
            for context_id in frame_contexts(cdp):
                try:
                    value = evaluate(cdp, context_id, "document.body ? document.body.innerText : ''")
                    if value:
                        texts.append(value)
                except Exception:
                    pass
            combined = "\n".join(texts)
            try:
                amount, evidence = calculate_amount(combined)
                evidence["target_url"] = target.get("url", "")
                return amount, evidence
            except ValueError as exc:
                last_error = str(exc)
        raise RuntimeError(last_error)
    finally:
        cdp.close()


def inspect_query_input(query_value: str, port: int) -> dict:
    """Fill only the account field and report radio state; never submit."""
    target = find_business_target(port)
    cdp = Cdp(target["webSocketDebuggerUrl"])
    try:
        cdp.call("Page.enable")
        for context_id in frame_contexts(cdp):
            result = evaluate(cdp, context_id, INSPECT_SCRIPT % json.dumps(query_value, ensure_ascii=False))
            if result and result.get("found"):
                return result
        raise RuntimeError("没有找到“按账户查询”后方的输入框")
    finally:
        cdp.close()


def atomic_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


@dataclass
class Agent:
    bridge: Path
    port: int = 9222

    def prepare(self):
        for name in ("requests", "processing", "results", "logs"):
            (self.bridge / name).mkdir(parents=True, exist_ok=True)

    def process(self, request_file: Path):
        task_id = request_file.stem
        processing = self.bridge / "processing" / request_file.name
        try:
            request_file.replace(processing)
        except FileNotFoundError:
            return
        try:
            task = json.loads(processing.read_text(encoding="utf-8"))
            if task.get("task_id") != task_id:
                raise ValueError("文件名与任务编号不一致")
            query_value = str(task.get("query_value") or "").strip()
            if not re.fullmatch(r"\d{6,24}", query_value):
                raise ValueError("查询号码格式无效")
            amount, evidence = run_query(query_value, self.port)
            result = {**task, "ok": True, "amount": amount, "evidence": evidence}
        except Exception as exc:
            result = {"task_id": task_id, "ok": False, "error": str(exc)}
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        atomic_json(self.bridge / "results" / f"{task_id}.json", result)
        processing.unlink(missing_ok=True)

    def run(self, once=False):
        self.prepare()
        while True:
            for path in sorted((self.bridge / "requests").glob("*.json")):
                self.process(path)
            if once:
                return
            time.sleep(0.7)


def main():
    parser = argparse.ArgumentParser(description="晨的小助手：业务系统缴费金额查询代理")
    parser.add_argument("--bridge", type=Path, default=DEFAULT_BRIDGE)
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--query", help="诊断模式：立即查询一个账号并在窗口显示结果")
    parser.add_argument("--inspect-query", help="安全诊断：只填写账号并报告查询方式，不点击确定")
    args = parser.parse_args()
    if args.inspect_query:
        query_value = str(args.inspect_query).strip()
        if not re.fullmatch(r"\d{6,24}", query_value):
            raise ValueError("查询号码格式无效，应为6至24位数字")
        result = inspect_query_input(query_value, args.port)
        print("安全诊断完成：没有点击确定，也没有发起查询。")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.query:
        query_value = str(args.query).strip()
        if not re.fullmatch(r"\d{6,24}", query_value):
            raise ValueError("查询号码格式无效，应为6至24位数字")
        amount, evidence = run_query(query_value, args.port)
        print(json.dumps({"ok": True, "amount": amount, "evidence": evidence}, ensure_ascii=False, indent=2))
        return
    Agent(args.bridge, args.port).run(args.once)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
