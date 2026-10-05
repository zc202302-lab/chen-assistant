"""One member operation; no shared-file clearing or software updating."""
import json
import time
from member_models import AutomationError, UncertainSubmission, MemberTask
from member_browser import Cdp, SearchRefreshGuard, _find_targets, _contexts, _evaluate
from member_page import _SEARCH_MATCH, _FIND_SEARCH_INPUT, _SET_SEARCH_AND_CLICK, _CLICK_LABEL, _MEMBER_DUPLICATE, _FILL_LABEL_INPUT, _READ_NAME, _HAS_SERVICE_INPUT, _SELECT_CONTACT, _CLICK_CONFIRM, _READ_OUTCOME, _GROUP_IDENTITIES
FORM_MARKER = "/toAddSubsman.action"

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

    def _group_matches(self, target: dict, group: str) -> bool:
        cdp = Cdp(target["webSocketDebuggerUrl"])
        try:
            cdp.call("Page.enable")
            identities = set()
            for context in _contexts(cdp):
                values = _evaluate(cdp, _GROUP_IDENTITIES, context)
                if isinstance(values, list):
                    identities.update(str(value) for value in values)
            return identities == {group}
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

    def _submit(self, target: dict, main_target: dict, service_number: str, group: str) -> tuple[str, str]:
        self._action(target, _SELECT_CONTACT, "人工识别真实性下拉框未找到")
        if not self._group_matches(main_target, group):
            raise AutomationError("当前集团身份未确认，未点击确定")
        try:
            self._action(target, _CLICK_CONFIRM, "页面下方“确定”按钮不唯一或不存在")
            return self._verify_submission(target, main_target, service_number, group)
        except UncertainSubmission:
            raise
        except Exception as exc:
            raise UncertainSubmission("确定操作或回执检查异常；请人工核对，禁止自动重试") from exc

    def _verify_submission(self, target, main_target, service_number, group):
        deadline = time.time() + 12
        while time.time() < deadline:
            _, targets = _find_targets(self.port)
            still_open = any(x.get("id") == target.get("id") for x in targets)
            if not still_open:
                verify_deadline = time.time() + 5
                while time.time() < verify_deadline:
                    if self._group_matches(main_target, group) and self._with_context(main_target, _MEMBER_DUPLICATE % json.dumps(service_number)):
                        return "已添加", "录入窗口关闭，成员列表已确认号码存在"
                    time.sleep(0.4)
                raise UncertainSubmission("录入窗口已关闭，但成员列表未确认号码；请人工核对，禁止自动重试")
            outcome = self._with_context(target, _READ_OUTCOME)
            if self._group_matches(main_target, group) and self._with_context(main_target, _MEMBER_DUPLICATE % json.dumps(service_number)):
                return "已添加", "目标集团成员列表已确认号码存在"
            if outcome and outcome.get("error"):
                raise UncertainSubmission("点击确定后系统显示错误；请人工核对成员列表，禁止自动重试")
            time.sleep(0.5)
        raise UncertainSubmission("已点击确定但没有收到成功回执；请人工核对成员列表，禁止自动重试")

    def add_one(self, task: MemberTask) -> tuple[str, str]:
        main, _ = _find_targets(self.port)
        with SearchRefreshGuard(self.port) as guard:
            self._action(main, _SET_SEARCH_AND_CLICK % json.dumps(task.group_search, ensure_ascii=False), "顶部集团搜索框或搜索按钮不唯一")
            started = time.time()
            deadline = started + 25
            while time.time() < deadline:
                if guard.error:
                    raise AutomationError("搜索刷新监听失败：" + guard.error)
                check = self._group_matches(main, task.group_search)
                if check and time.time() - started >= 2:
                    break
                time.sleep(0.4)
            else:
                raise AutomationError("搜索后未能唯一确认当前集团编号；未执行新增")
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
        if not self._group_matches(main, task.group_search):
            raise AutomationError("成员页面集团身份未确认，未执行新增")
        duplicate = self._with_context(main, _MEMBER_DUPLICATE % json.dumps(task.service_number))
        if duplicate:
            return "已存在，跳过", "成员列表中已找到该服务号码"

        self._action(main, _CLICK_LABEL % json.dumps("新增", ensure_ascii=False), "成员列表“新增”按钮不唯一或不存在")
        form = self._find_form_target(main)
        self._action(form, _FILL_LABEL_INPUT % (json.dumps("服务号码", ensure_ascii=False), json.dumps(task.service_number)), "服务号码输入框未找到")
        name = self._wait_loaded_name(form)
        status, detail = self._submit(form, main, task.service_number, task.group_search)
        return status, f"{name} · {detail}"


