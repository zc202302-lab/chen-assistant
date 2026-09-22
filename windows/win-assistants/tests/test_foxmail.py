import base64
import hashlib
import json
import unittest
import urllib.error
import urllib.request

from win_assistants.foxmail import (
    FoxmailBridge,
    build_mailto_uri,
    is_allowed_origin,
    safe_attachment_name,
    validate_compose_payload,
)


def _payload() -> dict[str, str]:
    content = "13800138000|65\r\n".encode()
    encode = lambda value: base64.b64encode(value.encode()).decode()
    return {
        "recipient_b64": encode("pay@example.com"),
        "subject_b64": encode("九月缴费"),
        "body_b64": encode("请查收"),
        "attachment_filename_b64": encode("客户缴费.txt"),
        "attachment_content_base64": base64.b64encode(content).decode(),
        "attachment_sha256": hashlib.sha256(content).hexdigest(),
    }


class FoxmailTests(unittest.TestCase):
    def test_origin_is_limited_to_product_domain_and_loopback(self):
        self.assertTrue(is_allowed_origin("https://assistant.ziboxiaozhushou.cn"))
        self.assertTrue(is_allowed_origin("http://localhost:8000"))
        self.assertFalse(is_allowed_origin("https://ziboxiaozhushou.cn.evil.example"))
        self.assertFalse(is_allowed_origin("file:///tmp/test"))
        self.assertFalse(is_allowed_origin(""))

    def test_payload_requires_exact_filename_and_sha256(self):
        values = validate_compose_payload(_payload())
        self.assertEqual(values[3], "客户缴费.txt")
        self.assertEqual(hashlib.sha256(values[4]).hexdigest(), values[5])
        changed = _payload()
        changed["attachment_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            validate_compose_payload(changed)
        unsafe_name = _payload()
        unsafe_name["attachment_filename_b64"] = base64.b64encode("客户:缴费.txt".encode()).decode()
        with self.assertRaisesRegex(ValueError, "filename changed"):
            validate_compose_payload(unsafe_name)

    def test_filename_and_mailto_contract(self):
        self.assertEqual(safe_attachment_name("a:b.txt"), "a_b.txt")
        uri = build_mailto_uri("pay@example.com", "九月 缴费", "第一行\n第二行")
        self.assertTrue(uri.startswith("mailto:pay%40example.com?"))
        self.assertIn("subject=", uri)
        self.assertIn("%3Cbr%3E", uri)

    def test_http_bridge_health_compose_and_origin(self):
        received = []

        def composer(payload):
            received.append(payload)
            return {"ok": True, "verified": True}

        bridge = FoxmailBridge(port=0, composer=composer)
        ok, _detail = bridge.start()
        self.assertTrue(ok)
        base = f"http://127.0.0.1:{bridge.port}"
        try:
            request = urllib.request.Request(base + "/health", headers={"Origin": "https://assistant.ziboxiaozhushou.cn"})
            with urllib.request.urlopen(request, timeout=2) as response:
                health = json.loads(response.read())
            self.assertEqual(health["version"], "0.9")
            self.assertFalse(health["auto_send"])

            body = json.dumps(_payload()).encode()
            request = urllib.request.Request(
                base + "/compose",
                data=body,
                headers={"Origin": "https://assistant.ziboxiaozhushou.cn", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                result = json.loads(response.read())
            self.assertTrue(result["verified"])
            self.assertEqual(len(received), 1)

            denied = urllib.request.Request(base + "/health", headers={"Origin": "https://evil.example"})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(denied, timeout=2)
            self.assertEqual(error.exception.code, 403)
        finally:
            bridge.stop()


if __name__ == "__main__":
    unittest.main()
