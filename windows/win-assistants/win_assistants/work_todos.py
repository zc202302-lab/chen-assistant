"""Desktop todo polling; workers never touch Tk and never overwrite offline data."""
import json
import queue
import threading
import urllib.request
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('待办接口不允许重定向，请检查网站地址')


def api_url(server):
    value = str(server).strip().rstrip('/')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1'})) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('请填写 HTTPS 网站根地址，例如 https://ziboxiaozhushou.cn')
    return value + '/api/work-todos'


def request_todos(server, token, item_id=None, payload=None, timeout=12):
    if not token:
        raise ValueError('请先填写待办专用连接码')
    url = api_url(server) + (f'/{int(item_id)}' if item_id is not None else '')
    req = urllib.request.Request(url, data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'Cache-Control': 'no-cache'})
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('待办数据过大，请在网页版整理后重试')
    result = json.loads(raw)
    if not isinstance(result, dict) or result.get('ok') is not True or not isinstance(result.get('items'), list):
        raise ValueError('待办接口返回无效')
    return result


class TodoReceiver:
    def __init__(self):
        self.events = queue.Queue()
        self._stop = threading.Event()
        self._generation = 0
        self._wake = threading.Event()

    def stop(self):
        self._stop.set()
        self._wake.set()
        self._generation += 1

    def start(self, server, token):
        self.stop()
        stop, wake = threading.Event(), threading.Event()
        self._stop, self._wake = stop, wake
        while True:
            try:
                self.events.get_nowait()
            except queue.Empty:
                break
        generation = self._generation
        def run():
            while not stop.is_set():
                try:
                    result = request_todos(server, token)
                    event = ('snapshot', result)
                except Exception as exc:
                    event = ('error', '同步失败，请检查网络或待办连接码：' + str(exc))
                if generation == self._generation and not stop.is_set():
                    self.events.put(event)
                wake.wait(15)
                wake.clear()
        threading.Thread(target=run, daemon=True, name='work-todos').start()

    def refresh(self):
        self._wake.set()
