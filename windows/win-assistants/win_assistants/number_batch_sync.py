"""Signed successful-write receipts with a durable, retryable outbox (no phone data)."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .number_batch import file_lock, _stage


def signed_receipt(body, count, token, completed_at=None):
    receipt = {'nonce': body['payload']['nonce'], 'request_signature': body['signature'],
               'count': count, 'completed_at': int(time.time()) if completed_at is None else completed_at}
    data = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return {'receipt': receipt, 'signature': hmac.new(token.encode(), b'number-batch-complete-v1\n' + data, hashlib.sha256).hexdigest()}


class ReceiptOutbox:
    def __init__(self, path, token_provider, server_provider=None):
        self.path = Path(path)
        self.token_provider = token_provider
        self.server_provider = server_provider
        self.stop_event = threading.Event()
        self.thread = None

    def _read(self):
        value = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        if not isinstance(value, dict):
            raise ValueError('批量回执记录损坏，请联系维护人员检查')
        return value

    def _save(self, value):
        staged = _stage(self.path, json.dumps(value).encode())
        try:
            staged.replace(self.path)
        finally:
            staged.unlink(missing_ok=True)

    def prepare(self):
        # Fail before workbook writes if the outbox is unreadable/unwritable.
        with file_lock(self.path):
            self._save(self._read())

    def add(self, body):
        with file_lock(self.path):
            entries = self._read()
            entries[body['receipt']['nonce']] = body
            self._save(entries)

    def deliver(self, body):
        from .number_batch_bridge import ORIGINS
        api_url = self.server_provider() if self.server_provider else ''
        parsed = urllib.parse.urlsplit(api_url)
        origin = f'{parsed.scheme}://{parsed.netloc}'
        if origin not in ORIGINS or parsed.path != '/api/number-inbox/pending' or parsed.query or parsed.fragment:
            raise ValueError('号码提醒接口地址无效，无法同步已录状态')
        request = urllib.request.Request(origin + '/api/number-inbox/batch-complete',
            data=json.dumps(body).encode(), method='POST',
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {self.token_provider()}',
                     'User-Agent': 'win-assistants-number-batch/1'})
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.loads(response.read(4096))
        if not isinstance(result, dict) or result.get('ok') is not True or result.get('archived') is not True:
            raise ValueError('已录状态同步尚未确认')

    def flush(self):
        if not self.server_provider:
            return
        with file_lock(self.path):
            entries = self._read()
        for nonce, body in entries.items():
            if self.stop_event.is_set():
                break
            try:
                self.deliver(body)
            except Exception:
                continue  # Keep successful-write evidence; never repeat workbook writes.
            with file_lock(self.path):
                current = self._read()
                if current.get(nonce) == body:
                    current.pop(nonce)
                    self._save(current)

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.flush()
            except Exception:
                pass
            self.stop_event.wait(15)

    def start(self):
        if not self.server_provider or (self.thread and self.thread.is_alive()):
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name='number-batch-receipts')
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=12)
            self.thread = None
