import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from windows.payment_query_agent import calculate_amount, next_five_band


def test_next_five_band():
    assert next_five_band(60) == 65
    assert next_five_band(62.12) == 65
    assert next_five_band(65) == 70
    assert next_five_band(69.99) == 70


def test_afterpaid_prefers_receivable():
    amount, evidence = calculate_amount(
        "产品类型 后付费新飞享+套餐\n应收金额 63.00\n未出账话费 38.10"
    )
    assert amount == 65
    assert evidence["raw_amount"] == 63.0


def test_afterpaid_uses_unbilled_when_receivable_zero():
    amount, evidence = calculate_amount(
        "产品类型 后付费\n应收金额 0.00\n未出账话费 38.10"
    )
    assert amount == 40
    assert evidence["raw_amount"] == 38.1


def test_afterpaid_detects_product_across_table_lines():
    amount, evidence = calculate_amount(
        "产品类型\n淄博后付费全球通新国内套餐\n集团用户号码\n"
        "未出账话费 136.00\n应收金额 0.00"
    )
    assert amount == 140
    assert evidence["product_type"] == "后付费"
    assert evidence["raw_amount"] == 136.0


def test_prepaid_uses_maximum_in_bill_section():
    amount, evidence = calculate_amount(
        "产品类型 预付费\n应结账单\n费用合计 62.12\n未销账金额 38.10\n合计 100.22"
    )
    assert amount == 105
    assert evidence["raw_amount"] == 100.22


def test_route_is_registered():
    from app.main import app

    matches = [
        route for route in app.router.routes
        if getattr(route, "path", "") == "/services/{service_id}/payment-auto-query-result"
        and "POST" in getattr(route, "methods", set())
    ]
    assert matches
    assert matches[0].endpoint.__name__ == "apply_payment_auto_query_result"


if __name__ == "__main__":
    test_next_five_band()
    test_afterpaid_prefers_receivable()
    test_afterpaid_uses_unbilled_when_receivable_zero()
    test_afterpaid_detects_product_across_table_lines()
    test_prepaid_uses_maximum_in_bill_section()
    test_route_is_registered()
    print("payment auto-query checks passed")
