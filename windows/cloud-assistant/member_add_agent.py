from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import sys
import time
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

try:
    import websocket
except ImportError:  # pragma: no cover - provided by the Windows build
    websocket = None


DEFAULT_BRIDGE = Path(r"Y:\ChenBridge")
BUSINESS_MARKER = "10.19.89.56/esop/"
FORM_MARKER = "/toAddSubsman.action"
XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


class AutomationError(RuntimeError):
    """A pre-submit page or field could not be matched safely."""


class UncertainSubmission(AutomationError):
    """The final submit was clicked but the system did not confirm its outcome."""


@dataclass(frozen=True)
class MemberTask:
    row_number: int
    service_number: str
    group_search: str


def _xml_text(root: ET.Element) -> str:
    return "".join(node.text or "" for node in root.iter(f"{{{XLSX_NS}}}t"))


def _column_number(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref.upper())
    if not letters:
        return 0
    value = 0
    for char in letters.group(0):
        value = value * 26 + ord(char) - ord("A") + 1
    return value


def read_member_tasks_xlsx(path: Path) -> list[MemberTask]:
    """Read the no-header A=service number, B=group search value workbook."""
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("任务文件不是有效的 .xlsx 工作簿") from exc
    with archive:
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names:
            raise ValueError("任务文件缺少工作簿内容")
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in relations.findall(f"{{{PKG_REL_NS}}}Relationship")}
        sheets = workbook.findall(f"{{{XLSX_NS}}}sheets/{{{XLSX_NS}}}sheet")
        if not sheets:
            raise ValueError("任务文件没有工作表")
        relation_id = sheets[0].attrib.get(f"{{{REL_NS}}}id", "")
        target = relmap.get(relation_id, "")
        if not target:
            raise ValueError("无法定位任务工作表")
        sheet_path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
        if sheet_path not in names:
            raise ValueError("任务工作表文件不存在")

        shared_strings = []
        if "xl/sharedStrings.xml" in names:
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = [_xml_text(si) for si in shared_root.findall(f"{{{XLSX_NS}}}si")]

        sheet = ET.fromstring(archive.read(sheet_path))
        tasks: list[MemberTask] = []
        for row in sheet.findall(f".//{{{XLSX_NS}}}sheetData/{{{XLSX_NS}}}row"):
            row_number = int(row.attrib.get("r", "0") or 0)
            values: dict[int, str] = {}
            for cell in row.findall(f"{{{XLSX_NS}}}c"):
                column = _column_number(cell.attrib.get("r", ""))
                if column not in (1, 2):
                    continue
                cell_type = cell.attrib.get("t", "")
                if cell_type == "inlineStr":
                    value = _xml_text(cell.find(f"{{{XLSX_NS}}}is")) if cell.find(f"{{{XLSX_NS}}}is") is not None else ""
                else:
                    raw = cell.find(f"{{{XLSX_NS}}}v")
                    value = raw.text or "" if raw is not None else ""
                    if cell_type == "s" and value:
                        try:
                            value = shared_strings[int(value)]
                        except (ValueError, IndexError):
                            raise ValueError(f"第 {row_number} 行共享字符串索引无效")
                values[column] = value.strip()

            service_number = values.get(1, "")
            group_search = values.get(2, "")
            if not service_number and not group_search:
                continue
            if not re.fullmatch(r"\d{5,20}", service_number):
                raise ValueError(f"第 {row_number} 行 A 列不是 5 至 20 位数字号码")
            if not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", group_search):
                raise ValueError(f"第 {row_number} 行 B 列集团搜索值格式无效")
            tasks.append(MemberTask(row_number, service_number, group_search))
        if not tasks:
            raise ValueError("任务文件中没有可执行号码")
        return tasks


def _json_url(url: str) -> list[dict]:
    with urllib.request.urlopen(url, timeout=4) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, list):
        raise RuntimeError("浏览器调试接口没有返回页面列表")
    return value


def _find_targets(port: int) -> tuple[dict, list[dict]]:
    targets = [x for x in _json_url(f"http://127.0.0.1:{port}/json/list") if x.get("type") == "page"]
    main = next((x for x in targets if BUSINESS_MARKER in str(x.get("url", ""))), None)
    if not main:
        raise RuntimeError("未找到已登录的集团客户系统页面；请先打开业务系统并保持会话有效")
    return main, targets


class Cdp:
    def __init__(self, ws_url: str):
        if websocket is None:
            raise RuntimeError("缺少 websocket-client 依赖")
        self.ws = websocket.create_connection(ws_url, timeout=8, suppress_origin=True)
        self.sequence = 0

    def call(self, method: str, params: dict | None = None) -> dict:
        self.sequence += 1
        call_id = self.sequence
        self.ws.send(json.dumps({"id": call_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") != call_id:
                continue
            if "error" in message:
                raise RuntimeError(f"浏览器命令失败：{method}")
            return message.get("result", {})

    def close(self):
        self.ws.close()


def _frame_ids(tree: dict) -> list[str]:
    found: list[str] = []

    def walk(node: dict):
        frame_id = node.get("frame", {}).get("id")
        if frame_id:
            found.append(frame_id)
        for child in node.get("childFrames") or []:
            walk(child)

    walk(tree)
    return found


def _contexts(cdp: Cdp) -> list[int]:
    tree = cdp.call("Page.getFrameTree").get("frameTree", {})
    result = []
    for frame_id in _frame_ids(tree):
        try:
            world = cdp.call("Page.createIsolatedWorld", {"frameId": frame_id, "worldName": "chen-member-agent"})
            result.append(int(world["executionContextId"]))
        except Exception:
            continue
    return result


def _evaluate(cdp: Cdp, expression: str, context_id: int | None = None):
    params = {"expression": expression, "returnByValue": True, "awaitPromise": True}
    if context_id is not None:
        params["contextId"] = context_id
    result = cdp.call("Runtime.evaluate", params)
    if result.get("exceptionDetails"):
        raise AutomationError("业务页面控件脚本执行失败")
    return result.get("result", {}).get("value")


_FIND_SEARCH_INPUT = r"""(() => {
  const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
  const inputs=[...document.querySelectorAll('input')].filter(e=>visible(e)&&!['hidden','button','submit','radio','checkbox'].includes(e.type));
  const exact=inputs.filter(e=>(e.placeholder||'').includes('您要查询的信息'));
  if(exact.length===1)return {ok:true,selector:'placeholder',value:exact[0].value||''};
  const buttons=[...document.querySelectorAll('button,input[type=button],input[type=submit],a')].filter(visible).filter(e=>(e.innerText||e.value||'').replace(/\s/g,'')==='搜索');
  if(buttons.length!==1)return {ok:false,reason:'搜索按钮不唯一'};
  const br=buttons[0].getBoundingClientRect();
  const candidates=inputs.map(e=>{const r=e.getBoundingClientRect();return {e,r,score:Math.abs((r.top+r.bottom-br.top-br.bottom)/2)+Math.abs(br.left-r.right)/10}})
   .filter(x=>x.r.right<=br.left&&Math.abs((x.r.top+x.r.bottom-br.top-br.bottom)/2)<=18).sort((a,b)=>a.score-b.score);
  if(!candidates.length)return {ok:false,reason:'搜索框未找到'};
  if(candidates.length>1&&Math.abs(candidates[0].score-candidates[1].score)<1)return {ok:false,reason:'搜索框匹配不唯一'};
  return {ok:true,selector:'geometry',value:candidates[0].e.value||''};
})()"""

_SET_SEARCH_AND_CLICK = r"""((queryValue) => {
  const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
  const compact=s=>String(s||'').replace(/\s/g,'');
  const inputs=[...document.querySelectorAll('input')].filter(e=>visible(e)&&!['hidden','button','submit','radio','checkbox'].includes(e.type));
  const exact=inputs.filter(e=>(e.placeholder||'').includes('您要查询的信息'));
  let input=exact.length===1?exact[0]:null;
  const buttons=[...document.querySelectorAll('button,input[type=button],input[type=submit],a')].filter(visible).filter(e=>compact(e.innerText||e.value)==='搜索');
  if(buttons.length!==1)return {ok:false,reason:'搜索按钮不唯一'};
  if(!input){const br=buttons[0].getBoundingClientRect();const c=inputs.map(e=>{const r=e.getBoundingClientRect();return {e,r,dy:Math.abs((r.top+r.bottom-br.top-br.bottom)/2)}}).filter(x=>x.r.right<=br.left&&x.dy<=18).sort((a,b)=>a.dy-b.dy);if(!c.length||(c.length>1&&Math.abs(c[0].dy-c[1].dy)<1))return {ok:false,reason:'搜索框未找到或不唯一'};input=c[0].e;}
  const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;setter.call(input,queryValue);input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));buttons[0].click();return {ok:true};
})(%s)"""

_CLICK_LABEL = r"""((labelText) => {
 const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
 const compact=e=>(e.innerText||e.value||e.textContent||'').replace(/\s+/g,' ').trim();
 const all=[...document.querySelectorAll('a,button,input[type=button],input[type=submit],[role=tab],li,span,div,td')].filter(visible).filter(e=>compact(e)===labelText);
 const minimal=all.filter(e=>![...e.children].some(c=>compact(c)===labelText));
 const candidates=minimal.length?minimal:all;
 if(candidates.length!==1)return {ok:false,count:candidates.length};
 let target=candidates[0];
 for(let i=0;i<4&&target.parentElement;i++){if(target.matches('a,button,[role=tab]'))break;target=target.parentElement;if(target.matches('a,button,[role=tab]'))break;}
 target.click();return {ok:true};
})(%s)"""

_MEMBER_DUPLICATE = r"""((number) => {
 const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
 const rows=[...document.querySelectorAll('tr')].filter(visible);
 return rows.some(row=>[...row.querySelectorAll('td')].some(cell=>(cell.innerText||cell.textContent||'').replace(/\s/g,'')===number));
})(%s)"""

_FILL_LABEL_INPUT = r"""((labelText,value) => {
 const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
 const clean=e=>(e.innerText||e.textContent||'').replace(/\s+/g,'').replace(/[：:]$/,'');
 const labels=[...document.querySelectorAll('td,th,label,span,div')].filter(visible).filter(e=>clean(e)===labelText);
 const controls=[...document.querySelectorAll('input')].filter(e=>visible(e)&&!['hidden','button','submit','radio','checkbox'].includes(e.type));
 const pairs=[];
 for(const label of labels){const lr=label.getBoundingClientRect();for(const control of controls){const r=control.getBoundingClientRect();const dy=Math.abs((lr.top+lr.bottom-r.top-r.bottom)/2);if(r.left>=lr.right-2&&dy<=22)pairs.push({label,control,score:dy+Math.max(0,r.left-lr.right)/100});}}
 pairs.sort((a,b)=>a.score-b.score);
 if(!pairs.length)return {ok:false,reason:`${labelText}输入框不存在`};
 const best=pairs[0].score;const winners=[...new Set(pairs.filter(x=>x.score<=best+0.25).map(x=>x.control))];
 if(winners.length!==1)return {ok:false,reason:`${labelText}输入框不唯一`};
 const input=winners[0];const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;setter.call(input,value);
 input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));input.dispatchEvent(new Event('blur',{bubbles:true}));
 return {ok:true};
})(%s,%s)"""

_READ_NAME = r"""(() => {
 const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
 const clean=e=>(e.innerText||e.textContent||'').replace(/\s+/g,'').replace(/[：:]$/,'');
 const labels=[...document.querySelectorAll('td,th,label,span,div')].filter(visible).filter(e=>clean(e)==='姓名');
 const inputs=[...document.querySelectorAll('input')].filter(e=>visible(e)&&!['hidden','button','submit','radio','checkbox'].includes(e.type));
 const pairs=[];for(const label of labels){const lr=label.getBoundingClientRect();for(const input of inputs){const r=input.getBoundingClientRect();const dy=Math.abs((lr.top+lr.bottom-r.top-r.bottom)/2);if(r.left>=lr.right-2&&dy<=22)pairs.push({input,score:dy+Math.max(0,r.left-lr.right)/100});}}
 pairs.sort((a,b)=>a.score-b.score);return pairs.length?{value:pairs[0].input.value||''}:{value:''};
})()"""

_HAS_SERVICE_INPUT = r"""(() => {
 const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
 const clean=e=>(e.innerText||e.textContent||'').replace(/\s+/g,'').replace(/[：:]$/,'');
 const labels=[...document.querySelectorAll('td,th,label,span,div')].filter(visible).filter(e=>clean(e)==='服务号码');
 const inputs=[...document.querySelectorAll('input')].filter(e=>visible(e)&&!['hidden','button','submit','radio','checkbox'].includes(e.type));
 return labels.some(label=>{const lr=label.getBoundingClientRect();return inputs.some(input=>{const r=input.getBoundingClientRect();return r.left>=lr.right-2&&Math.abs((lr.top+lr.bottom-r.top-r.bottom)/2)<=22;});});
})()"""

_SELECT_CONTACT = r"""(() => {
 const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
 const clean=e=>(e.innerText||e.textContent||'').replace(/\s+/g,'').replace(/[：:]$/,'');
 const labels=[...document.querySelectorAll('td,th,label,span,div')].filter(visible).filter(e=>clean(e)==='人工识别真实性');
 const selects=[...document.querySelectorAll('select')].filter(visible);const pairs=[];
 for(const label of labels){const lr=label.getBoundingClientRect();for(const select of selects){const r=select.getBoundingClientRect();const dy=Math.abs((lr.top+lr.bottom-r.top-r.bottom)/2);if(r.left>=lr.right-2&&dy<=24)pairs.push({select,score:dy+Math.max(0,r.left-lr.right)/100});}}
 pairs.sort((a,b)=>a.score-b.score);if(!pairs.length)return {ok:false,reason:'人工识别真实性下拉框未找到'};
 const best=pairs[0].score;const winners=[...new Set(pairs.filter(x=>x.score<=best+0.25).map(x=>x.select))];if(winners.length!==1)return {ok:false,reason:'人工识别真实性下拉框不唯一'};
 const select=winners[0];const options=[...select.options].filter(o=>(o.textContent||'').replace(/\s/g,'')==='集团通讯录');if(options.length!==1)return {ok:false,reason:'没有唯一的“集团通讯录”选项'};
 select.value=options[0].value;select.dispatchEvent(new Event('input',{bubbles:true}));select.dispatchEvent(new Event('change',{bubbles:true}));return {ok:true};
})()"""

_CLICK_CONFIRM = r"""(() => {
 const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
 const compact=e=>(e.innerText||e.value||'').replace(/\s/g,'');
 const buttons=[...document.querySelectorAll('button,input[type=button],input[type=submit],a')].filter(visible).filter(e=>compact(e)==='确定');
 if(buttons.length!==1)return {ok:false,count:buttons.length};
 buttons[0].click();return {ok:true};
})()"""

_READ_OUTCOME = r"""(() => {const text=(document.body?.innerText||'').replace(/\s+/g,'');return {success:/新增成功|添加成功|保存成功|操作成功/.test(text),duplicate:/已是成员|已经存在|重复添加/.test(text),error:/失败|错误|异常/.test(text)};})()"""


class MemberAdder:
    def __init__(self, port: int = 9222):
        self.port = port

    def _with_context(self, target: dict, script: str):
        cdp = Cdp(target["webSocketDebuggerUrl"])
        try:
            cdp.call("Page.enable")
            fallback = None
            for context in _contexts(cdp):
                try:
                    value = _evaluate(cdp, script, context)
                except Exception:
                    continue
                if value is None:
                    continue
                if isinstance(value, dict):
                    if (
                        value.get("ok") is True
                        or value.get("success")
                        or value.get("duplicate")
                        or value.get("error")
                        or bool(value.get("value"))
                    ):
                        return value
                    fallback = value
                    continue
                if value:
                    return value
                fallback = value
            return fallback
        finally:
            cdp.close()

    def _action(self, target: dict, script: str, fail: str):
        result = self._with_context(target, script)
        if not result or not result.get("ok"):
            detail = (result or {}).get("reason") or fail
            raise AutomationError(detail)
        return result

    def _find_form_target(self, main_target: dict, timeout: float = 10.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, targets = _find_targets(self.port)
            popup = next((x for x in targets if FORM_MARKER in str(x.get("url", ""))), None)
            if popup:
                return popup
            same = next((x for x in targets if x.get("id") == main_target.get("id")), None)
            if same:
                # Some browser builds render the form in the existing page.
                check = self._with_context(same, _HAS_SERVICE_INPUT)
                if check:
                    return same
            time.sleep(0.4)
        raise AutomationError("点击新增后没有打开成员录入窗口")

    def _wait_loaded_name(self, target: dict, timeout: float = 20.0) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            value = self._with_context(target, _READ_NAME)
            name = str((value or {}).get("value") or "").strip()
            if name:
                return name
            time.sleep(0.5)
        raise AutomationError("服务号码输入后，姓名在 20 秒内没有加载")

    def _submit(self, target: dict, main_target: dict, service_number: str) -> tuple[str, str]:
        self._action(target, _SELECT_CONTACT, "人工识别真实性下拉框未找到")
        self._action(target, _CLICK_CONFIRM, "页面下方“确定”按钮不唯一或不存在")
        deadline = time.time() + 12
        while time.time() < deadline:
            _, targets = _find_targets(self.port)
            still_open = any(x.get("id") == target.get("id") for x in targets)
            if not still_open:
                verify_deadline = time.time() + 5
                while time.time() < verify_deadline:
                    if self._with_context(main_target, _MEMBER_DUPLICATE % json.dumps(service_number)):
                        return "已添加", "录入窗口关闭，成员列表已确认号码存在"
                    time.sleep(0.4)
                raise UncertainSubmission("录入窗口已关闭，但成员列表未确认号码；请人工核对，禁止自动重试")
            outcome = self._with_context(target, _READ_OUTCOME)
            if outcome and outcome.get("success"):
                return "已添加", "系统显示提交成功"
            if outcome and outcome.get("duplicate"):
                return "已存在，跳过", "系统提示该号码已存在"
            if outcome and outcome.get("error"):
                raise UncertainSubmission("点击确定后系统显示错误；请人工核对成员列表，禁止自动重试")
            time.sleep(0.5)
        raise UncertainSubmission("已点击确定但没有收到成功回执；请人工核对成员列表，禁止自动重试")

    def add_one(self, task: MemberTask) -> tuple[str, str]:
        main, _ = _find_targets(self.port)
        self._action(main, _SET_SEARCH_AND_CLICK % json.dumps(task.group_search, ensure_ascii=False), "顶部集团搜索框或搜索按钮不唯一")
        deadline = time.time() + 15
        while time.time() < deadline:
            check = self._with_context(main, "(() => (document.body?.innerText||'').includes(%s))()" % json.dumps(task.group_search, ensure_ascii=False))
            if check:
                break
            time.sleep(0.4)
        else:
            raise AutomationError("搜索后页面没有出现指定集团编号")

        self._action(main, _CLICK_LABEL % json.dumps("成员信息", ensure_ascii=False), "成员信息入口不唯一或不存在")
        member_deadline = time.time() + 12
        while time.time() < member_deadline:
            member_list_ready = self._with_context(
                main,
                "(() => (document.body?.innerText||'').includes('成员列表'))()",
            )
            if member_list_ready:
                break
            time.sleep(0.4)
        else:
            raise AutomationError("成员信息页面没有加载出成员列表")
        duplicate = self._with_context(main, _MEMBER_DUPLICATE % json.dumps(task.service_number))
        if duplicate:
            return "已存在，跳过", "成员列表中已找到该服务号码"

        self._action(main, _CLICK_LABEL % json.dumps("新增", ensure_ascii=False), "成员列表“新增”按钮不唯一或不存在")
        form = self._find_form_target(main)
        self._action(form, _FILL_LABEL_INPUT % (json.dumps("服务号码", ensure_ascii=False), json.dumps(task.service_number)), "服务号码输入框未找到")
        name = self._wait_loaded_name(form)
        status, detail = self._submit(form, main, task.service_number)
        return status, f"{name} · {detail}"


@dataclass
class Agent:
    bridge: Path = DEFAULT_BRIDGE
    port: int = 9222

    def prepare(self):
        for folder in ("processing", "processed", "results", "errors", "logs"):
            (self.bridge / folder).mkdir(parents=True, exist_ok=True)

    def process(self, source: Path) -> Path | None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        claimed = self.bridge / "processing" / f"号码加集团_{stamp}_{uuid.uuid4().hex[:8]}.xlsx"
        try:
            source.replace(claimed)
        except (FileNotFoundError, PermissionError, OSError):
            return None

        batch_id = hashlib.sha256(claimed.read_bytes()).hexdigest()[:16]
        result_path = self.bridge / "results" / f"号码加集团_结果_{stamp}_{batch_id}.json"
        try:
            tasks = read_member_tasks_xlsx(claimed)
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
        return result_path

    def run(self, once: bool = False):
        self.prepare()
        while True:
            source = self.bridge / "号码加集团.xlsx"
            if source.exists():
                self.process(source)
                if once:
                    return
            elif once:
                return
            time.sleep(1.0)


def main():
    parser = argparse.ArgumentParser(description="云电脑助手：批量添加集团成员")
    parser.add_argument("--bridge", type=Path, default=DEFAULT_BRIDGE)
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--once", action="store_true", help="只处理当前号码加集团.xlsx 后退出")
    parser.add_argument("--check-file", type=Path, help="只校验 Excel 两列，不连接业务系统")
    args = parser.parse_args()
    if args.check_file:
        tasks = read_member_tasks_xlsx(args.check_file)
        print(json.dumps({"ok": True, "rows": len(tasks), "first_row": tasks[0].row_number}, ensure_ascii=False))
        return
    Agent(args.bridge, args.port).run(args.once)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
