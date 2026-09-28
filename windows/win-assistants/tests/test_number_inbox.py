import io
import json
import queue
import unittest
import urllib.error
from unittest.mock import patch

from win_assistants.config import NumberInboxConfig
from win_assistants.number_inbox import NumberInboxReceiver


class _Response:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return self._payload


class NumberInboxTests(unittest.TestCase):
    def test_fetch_uses_bearer_token_and_validates_payload(self):
        seen = {}

        def fake_urlopen(request, timeout=0):
            seen["authorization"] = request.headers.get("Authorization")
            seen["timeout"] = timeout
            return _Response({
                "ok": True,
                "pending_count": 2,
                "latest_id": 9,
                "items": [{"id": 9, "number": "13800138000", "submitter": "张三", "note": "新装"}],
            })

        settings = NumberInboxConfig(api_url="https://assistant.example/api/number-inbox/pending")
        with patch("win_assistants.number_inbox.urllib.request.urlopen", side_effect=fake_urlopen):
            payload = NumberInboxReceiver.fetch(settings, "secret-token")
        self.assertEqual(seen["authorization"], "Bearer secret-token")
        self.assertEqual(payload["latest_id"], 9)

    def test_first_poll_primes_without_new_notification(self):
        receiver = NumberInboxReceiver()
        settings = NumberInboxConfig(last_seen_id=0)
        payload = {
            "ok": True,
            "pending_count": 1,
            "latest_id": 8,
            "items": [{"id": 8, "number": "13800138000", "submitter": "张三", "note": ""}],
        }

        stop = type("Stop", (), {"is_set": lambda self: False, "wait": lambda self, _s: True})()
        receiver._generation = 1
        with patch.object(receiver, "fetch", return_value=payload):
            receiver._run(settings, "token", stop, 1)
        event = receiver.events.get_nowait()
        self.assertEqual(event.kind, "connected")
        self.assertEqual(event.item_id, 8)
        with self.assertRaises(queue.Empty):
            receiver.events.get_nowait()

    def test_unseen_items_emit_oldest_first(self):
        receiver = NumberInboxReceiver()
        settings = NumberInboxConfig(last_seen_id=5)
        payload = {
            "ok": True,
            "pending_count": 3,
            "latest_id": 8,
            "items": [
                {"id": 8, "number": "18800000008", "submitter": "乙", "note": ""},
                {"id": 7, "number": "18800000007", "submitter": "甲", "note": ""},
                {"id": 5, "number": "18800000005", "submitter": "", "note": ""},
            ],
        }
        stop = type("Stop", (), {"is_set": lambda self: False, "wait": lambda self, _s: True})()
        receiver._generation = 1
        with patch.object(receiver, "fetch", return_value=payload):
            receiver._run(settings, "token", stop, 1)
        events = [receiver.events.get_nowait(), receiver.events.get_nowait()]
        self.assertEqual([e.item_id for e in events], [7, 8])
        self.assertTrue(all(e.kind == "new" for e in events))

    def test_auth_failure_becomes_status_event(self):
        receiver = NumberInboxReceiver()
        settings = NumberInboxConfig(last_seen_id=1)
        error = urllib.error.HTTPError(settings.api_url, 401, "Unauthorized", {}, io.BytesIO())
        stop = type("Stop", (), {"is_set": lambda self: False, "wait": lambda self, _s: True})()
        receiver._generation = 1
        with patch.object(receiver, "fetch", side_effect=error):
            receiver._run(settings, "token", stop, 1)
        event = receiver.events.get_nowait()
        self.assertEqual(event.kind, "auth")
        self.assertIn("连接码无效", event.message)


if __name__ == "__main__":
    unittest.main()
