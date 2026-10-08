"""CDP connections, target discovery and narrowly matched refresh dialogs."""
import json
import re
import threading
import time
import urllib.request
try:
    import websocket
except ImportError:
    websocket = None
BUSINESS_MARKER = "10.19.89.56/esop/"

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
        self.events = []

    def call(self, method: str, params: dict | None = None, session_id: str | None = None) -> dict:
        self.sequence += 1
        call_id = self.sequence
        command = {"id": call_id, "method": method, "params": params or {}}
        if session_id:
            command["sessionId"] = session_id
        self.ws.send(json.dumps(command))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") != call_id:
                if message.get("method"):
                    self.events.append(message)
                continue
            if "error" in message:
                raise RuntimeError(f"浏览器命令失败：{method}")
            return message.get("result", {})

    def close(self):
        self.ws.close()



class SearchRefreshGuard:
    """Observe search popups before their scripts run; accept only the known refresh."""
    def __init__(self, port):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=4) as response:
            endpoint = json.load(response)["webSocketDebuggerUrl"]
        self.cdp = Cdp(endpoint)
        self.stopped = threading.Event()
        self.error = None
        self.sessions = {}

    def __enter__(self):
        self.cdp.call("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True})
        self.cdp.ws.settimeout(0.2)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def _handle(self, event):
        method = event.get("method")
        params = event.get("params", {})
        if method == "Target.attachedToTarget":
            session = params["sessionId"]
            info = params.get("targetInfo", {})
            self.sessions[session] = info
            try:
                if info.get("type") == "page":
                    self.cdp.call("Page.enable", session_id=session)
            finally:
                if params.get("waitingForDebugger"):
                    self.cdp.call("Runtime.runIfWaitingForDebugger", session_id=session)
        elif method == "Page.javascriptDialogOpening":
            session = event.get("sessionId")
            url = params.get("url", "")
            text = re.sub(r"\s", "", params.get("message", ""))
            if (session and url.startswith("https://10.19.89.56/")
                    and params.get("type") == "confirm"
                    and text.rstrip("?？") == "集团客户统一视图Tab页已打开，是否刷新"):
                self.cdp.call("Page.handleJavaScriptDialog", {"accept": True}, session)
                print("已确认集团视图刷新", flush=True)

    def _run(self):
        try:
            while not self.stopped.is_set():
                if self.cdp.events:
                    self.cdp.ws.settimeout(8)
                    self._handle(self.cdp.events.pop(0))
                    self.cdp.ws.settimeout(0.2)
                    continue
                try:
                    event = json.loads(self.cdp.ws.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                if event.get("method"):
                    self.cdp.ws.settimeout(8)
                    self._handle(event)
                    self.cdp.ws.settimeout(0.2)
        except Exception as exc:
            self.error = str(exc)

    def __exit__(self, *args):
        self.stopped.set()
        self.thread.join(timeout=10)
        try:
            if not self.thread.is_alive():
                self.cdp.ws.settimeout(4)
                self.cdp.call("Target.setAutoAttach", {"autoAttach": False, "waitForDebuggerOnStart": False, "flatten": True})
        finally:
            self.cdp.close()


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

