import json
import unittest

from win_assistants.config import SmsConfig
from win_assistants.sms import SmsReceiver, find_code, protect_secret, unprotect_secret


class SmsTests(unittest.TestCase):
    def test_find_code_prefers_labelled_code(self):
        self.assertEqual(find_code("订单 987654321，验证码为 482731，请勿泄露"), "482731")

    def test_find_code_supports_english_and_fallback(self):
        self.assertEqual(find_code("Your verification code is 173905"), "173905")
        self.assertEqual(find_code("本次登录使用 8642"), "8642")
        self.assertIsNone(find_code("没有任何数字"))

    def test_secret_round_trip_in_test_environment(self):
        protected = protect_secret("token-value")
        self.assertNotEqual(protected, "token-value")
        self.assertEqual(unprotect_secret(protected), "token-value")

    def test_build_url_escapes_channel_and_marker(self):
        settings = SmsConfig(server_base="https://sms.example.com/", channel="iphone code", marker="id/1")
        self.assertEqual(
            SmsReceiver.build_url(settings),
            "https://sms.example.com/iphone%20code/json?since=id%2F1",
        )

    def test_message_event_contains_code_and_marker(self):
        receiver = SmsReceiver()
        settings = SmsConfig()
        receiver._handle_line(json.dumps({"event": "message", "message": "验证码 556677", "id": "abc"}), settings)
        event = receiver.events.get_nowait()
        self.assertEqual(event.kind, "message")
        self.assertEqual(event.code, "556677")
        self.assertEqual(event.marker, "abc")


if __name__ == "__main__":
    unittest.main()
