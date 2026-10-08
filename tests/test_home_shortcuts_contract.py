"""Contract tests for home shortcut validation and safe section links."""
import unittest

from app.v101_workspace_routes import _validated_home_shortcuts


class HomeShortcutContractTests(unittest.TestCase):
    def test_cross_space_module_urls(self):
        values = [
            {"href": "/work/number-inbox", "title": "号码收集"},
            {"href": "/products", "title": "产品汇总"},
            {"href": "/customers", "title": "全部客户"},
            {"href": "/search", "title": "工作搜索"},
            {"href": "/info", "title": "资料"},
            {"href": "/life/recipes", "title": "菜谱"},
        ]
        self.assertEqual(_validated_home_shortcuts(values), values)

    def test_cannot_send_external_or_dynamic_content(self):
        for href in ("https://example.com", "//example.com", "/customers/123",
                     "/life/recipes/123", "/work/number-inbox?pending=1",
                     "/life/%2e%2e/admin", "/logout"):
            with self.subTest(href=href), self.assertRaises(ValueError):
                _validated_home_shortcuts([{"href": href, "title": "bad"}])

    def test_duplicate_and_over_limit_rejected(self):
        with self.assertRaises(ValueError):
            _validated_home_shortcuts([
                {"href": "/work", "title": "工作"},
                {"href": "/work", "title": "工作2"},
            ])
        with self.assertRaises(ValueError):
            _validated_home_shortcuts([{"href": "/work", "title": "工作"}] * 31)

    def test_shortcut_title_is_trimmed(self):
        self.assertEqual(_validated_home_shortcuts([{"href": "/life", "title": " 生活 "}]),
                         [{"href": "/life", "title": "生活"}])


if __name__ == "__main__":
    unittest.main()
