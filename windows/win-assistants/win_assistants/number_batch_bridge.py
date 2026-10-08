"""Authenticated loopback-only workbook bridge for the number inbox page."""
from __future__ import annotations

import hashlib
import hmac
import json
import queue
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import app_data_dir
from .number_batch_sync import ReceiptOutbox, signed_receipt
from .number_batch import file_lock, write_batch, _stage

ORIGINS = frozenset({'https://assistant.ziboxiaozhushou.cn', 'https://assistant.zbassistant.site', 'https://zbassistant.site'})
PORT = 18764


def verify_request(body, token, now=None):
    now = int(time.time()) if now is None else now
    if not token or not isinstance(body, dict) or set(body) != {'payload', 'signature'}:
        raise ValueError('请求未授权，请检查提醒连接码')
    payload, signature = body['payload'], body['signature']
    if not isinstance(payload, dict) or set(payload) != {'version', 'nonce', 'issued_at', 'groups', 'numbers', 'role', 'manual'}:
        raise ValueError('请求格式无效，请升级Windows助手')
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    expected = hmac.new(token.encode(), canonical, hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise ValueError('连接码不匹配，请重新填写网页设置中的提醒连接码')
    if type(payload['version']) is not int or payload['version'] != 1 or type(payload['issued_at']) is not int or not now - 600 <= payload['issued_at'] <= now + 60:
        raise ValueError('请求过期，请重新点击批量添加')
    if not isinstance(payload['nonce'], str) or not re.fullmatch('[a-f0-9]{32}', payload['nonce']):
        raise ValueError('请求编号无效')
    return payload


class NumberBatchBridge:
    def __init__(self, token_provider, target_provider, *, ledger=None, port=PORT, server_provider=None):
        self.token_provider = token_provider
        self.target_provider = target_provider
        self.ledger = Path(ledger) if ledger else app_data_dir() / 'number-batch-requests.json'
        self.port = port
        self.server = None
        self.thread = None
        self.busy = threading.Lock()
        self.events = queue.SimpleQueue()
        self.receipts = ReceiptOutbox(self.ledger.with_name(self.ledger.stem + "-receipts.json"), token_provider, server_provider)

    def execute(self, body):
        if not self.busy.acquire(blocking=False):
            raise ValueError('正在执行另一批写入，请稍后重试')
        try:
            token = self.token_provider()
            payload = verify_request(body, token)
            self.receipts.prepare()
            now = int(time.time())
            # Reserve durably before touching the workbook. Crashes cannot replay a batch.
            with file_lock(self.ledger):
                try:
                    known = json.loads(self.ledger.read_text(encoding='utf-8')) if self.ledger.exists() else {}
                    if not isinstance(known, dict) or any(not re.fullmatch('[a-f0-9]{32}', key) or type(value) is not int for key, value in known.items()):
                        raise ValueError()
                except (ValueError, TypeError):
                    raise ValueError('批量请求记录损坏，请联系维护人员检查，文件未写入')
                known = {key: value for key, value in known.items() if value >= now - 600}
                if payload['nonce'] in known:
                    raise ValueError('这批请求已执行过，请先检查Excel；需要重新生成时再次点击批量添加')
                if len(known) >= 5000:
                    raise ValueError('请求过于频繁，请稍后重试')
                known[payload['nonce']] = now + 60
                staged = _stage(self.ledger, json.dumps(known).encode())
                try:
                    staged.replace(self.ledger)
                finally:
                    staged.unlink(missing_ok=True)
            result = write_batch(self.target_provider(), payload['numbers'], payload['groups'], payload['role'], payload['manual'])
            result['receipt'] = signed_receipt(body, result['count'], token)
            try:
                self.receipts.add(result['receipt'])
            except (OSError, ValueError):
                # The file has already committed; return its signed evidence to
                # the browser instead of turning success into a false failure.
                result['sync_warning'] = '回执暂存失败，请保持网页打开完成状态同步'
            return result
        finally:
            self.busy.release()

    def start(self):
        if self.server:
            return True, '批量添加已就绪'
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def setup(self):
                super().setup()
                self.connection.settimeout(10)

            def allowed(self):
                host = self.headers.get('Host', '')
                return (self.headers.get('Origin') in ORIGINS and
                        host == f'127.0.0.1:{self.server.server_port}' and
                        self.client_address[0] == '127.0.0.1')

            def reply(self, status, body=None):
                data = json.dumps(body or {}, ensure_ascii=False).encode()
                self.send_response(status)
                if self.allowed():
                    self.send_header('Access-Control-Allow-Origin', self.headers['Origin'])
                    self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                    self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                    self.send_header('Access-Control-Allow-Private-Network', 'true')
                    self.send_header('Vary', 'Origin')
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_OPTIONS(self):
                self.reply(200 if self.allowed() and self.path in ('/health', '/number-batch') else 403)

            def do_GET(self):
                if not self.allowed():
                    return self.reply(403)
                self.reply(200, {'ok': True, 'batch_version': 1, 'receipt_version': 1}) if self.path == '/health' else self.reply(404)

            def do_POST(self):
                if not self.allowed():
                    return self.reply(403)
                if self.path != '/number-batch':
                    return self.reply(404)
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 1024 * 1024 or self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json' or self.headers.get('Transfer-Encoding'):
                        return self.reply(400, {'ok': False, 'error': '请求大小或格式无效'})
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise ValueError('请求不完整')
                    result = bridge.execute(json.loads(raw))
                except (ValueError, OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
                    result = {'ok': False, 'error': str(exc) or '写入失败，原文件未修改'}
                # A browser disconnect after the atomic write cannot turn a
                # successful local result into a false failure notification.
                bridge.events.put(result)
                self.reply(200 if result.get('ok') else 400, result)

        # Imports here keep the error surface bounded without logging phone data.
        import zipfile
        import xml.etree.ElementTree as ET
        try:
            self.server = ThreadingHTTPServer(('127.0.0.1', self.port), Handler)
            # server_close waits for accepted requests, including an atomic write.
            self.server.daemon_threads = False
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name='number-batch-bridge')
            self.thread.start()
            self.receipts.start()
            return True, '批量添加已就绪'
        except OSError as exc:
            self.server = None
            return False, f'批量添加本地连接失败：{exc}'

    def stop(self):
        server, self.server = self.server, None
        if server:
            server.shutdown()
            server.server_close()
        if self.thread:
            self.thread.join(timeout=2)
            self.thread = None
        self.receipts.stop()
