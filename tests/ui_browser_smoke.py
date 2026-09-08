from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "app.db"
for suffix in ("", "-wal", "-shm"):
    p = Path(str(DB) + suffix)
    if p.exists():
        p.unlink()

os.environ.setdefault("APP_USERNAME", "ui-test")
os.environ.setdefault("APP_PASSWORD_SALT", "dGVzdHNhbHQ=")
os.environ.setdefault("APP_PASSWORD_HASH", "not-used-by-this-test")
os.environ.setdefault("APP_SESSION_SECRET", "ui-test-session-secret")
os.environ.setdefault("APP_ENCRYPTION_KEY", "not-used-by-this-test")
os.environ.setdefault("APP_SECURE_COOKIE", "0")

from app.db import db, init_db, now_iso  # noqa: E402
from app.payment_v02 import current_period  # noqa: E402
from app.security import create_session  # noqa: E402


def month_add(d: date, months: int) -> date:
    idx = d.year * 12 + d.month - 1 + months
    year, month0 = divmod(idx, 12)
    return date(year, month0 + 1, 15)


def add_customer(conn, name: str, suffix: int) -> tuple[int, list[int]]:
    now = now_iso(); period = current_period()
    cur = conn.execute(
        "INSERT INTO customers (name,group_code,tax_id,payment_enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        (name, f"C000{suffix}", f"TEST-TAX-{suffix}", 1, now, now),
    )
    cid = int(cur.lastrowid); service_ids = []
    for idx, amount in enumerate((100, 200), 1):
        cur = conn.execute(
            """INSERT INTO services
               (customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,
                payment_cycle,payment_interval_months,active_from_period,sort_order,source_row)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, "成员", f"测试{idx}", f"1380000{suffix:02d}{idx:03d}", f"5338000{suffix:02d}{idx:03d}",
             amount, 0, "1个月", 1, period, idx * 10, idx),
        )
        sid = int(cur.lastrowid); service_ids.append(sid)
        conn.execute(
            "INSERT INTO service_payment_rules (service_id,effective_period,mode,fixed_amount,created_at) VALUES(?,?,?,?,?)",
            (sid, "1900-01", "variable", 0, now),
        )
    return cid, service_ids


def seed() -> tuple[int, int, str]:
    init_db(); now = now_iso()
    with db() as conn:
        c1, services = add_customer(conn, "UI测试客户A", 1)
        c2, _ = add_customer(conn, "UI测试客户B", 2)
        for name, expiry in (("已到期优惠", date.today().isoformat()),
                             ("即将到期优惠", month_add(date.today(), 2).isoformat()),
                             ("后续优惠不显示", month_add(date.today(), 4).isoformat())):
            conn.execute(
                """INSERT INTO promotions
                   (service_id,name,start_date,expiry_date,remind_days,status,notes,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (services[0], name, "", expiry, 60, "active", "", now),
            )
    token, _, _ = create_session(); return c1, c2, token


def wait_http(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout; last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as r:
                if r.status == 200: return
        except Exception as exc: last = exc
        time.sleep(0.2)
    raise RuntimeError(f"server did not start: {last}")


def read_width(page, key: str) -> int:
    value = page.eval_on_selector("#paymentSortable", """(el,key) => {
      const n=parseInt(getComputedStyle(el).getPropertyValue(`--col-${key}`).trim(),10);
      return Number.isFinite(n)?n:-1;
    }""", key)
    assert value > 0, f"invalid {key} width: {value}"; return int(value)


def near(a: float, b: float, tol: float, msg: str) -> None:
    assert abs(a-b) <= tol, f"{msg}: {a} vs {b}"


def clipboard(page) -> str:
    return page.evaluate("navigator.clipboard.readText()")


def main() -> None:
    cid, cid2, token = seed()
    server = subprocess.Popen([sys.executable,"-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8123"],
                              cwd=ROOT, env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        wait_http("http://127.0.0.1:8123/health")
        from playwright.sync_api import sync_playwright
        page_errors=[]; request_failures=[]
        with sync_playwright() as p:
            browser=p.chromium.launch(); context=browser.new_context(viewport={"width":1440,"height":1000})
            context.grant_permissions(["clipboard-read","clipboard-write"], origin="http://127.0.0.1:8123")
            context.add_cookies([{"name":"session_token","value":token,"url":"http://127.0.0.1:8123"}])
            page=context.new_page(); page.on("pageerror",lambda exc:page_errors.append(str(exc)))
            page.on("requestfailed",lambda req:request_failures.append(f"{req.method} {req.url}: {req.failure}"))

            page.goto(f"http://127.0.0.1:8123/customers/{cid}",wait_until="networkidle")
            assert page.locator(".v028-workspace").count()==1
            hrefs=page.locator('link[rel="stylesheet"]').evaluate_all("els=>els.map(x=>x.getAttribute('href'))")
            css_names=[x.split("?",1)[0].rsplit("/",1)[-1] for x in hrefs]
            assert css_names==["app.css","v028.css"],css_names
            forbidden={"v02.css","v021.css","v022.css","v023.css","v024.css","v025.css","v026.css","v027.css"}
            assert not forbidden.intersection(css_names),css_names

            # 前期核心复制功能必须持续可用：客户名称、集团编码、税号。
            hero_copies=page.locator('.v023-profile-card .copy-btn')
            expected=['UI测试客户A','C0001','TEST-TAX-1']
            assert hero_copies.count()>=3
            for i,value in enumerate(expected):
                hero_copies.nth(i).click(); page.wait_for_timeout(50)
                assert clipboard(page)==value, (i, clipboard(page), value)

            # 缴费号码/账号单击复制；复制时不能夺走正在编辑金额的焦点。
            first_payment=page.locator('[data-payment-row]').first
            amount=first_payment.locator('.quick-amount')
            amount.click(); assert page.evaluate('document.activeElement===arguments[0]', amount.element_handle())
            ids=first_payment.locator('.identifier-copy')
            assert ids.count()==2
            for i in range(2):
                value=ids.nth(i).get_attribute('data-copy')
                ids.nth(i).click(); page.wait_for_timeout(50)
                assert clipboard(page)==value
                assert page.evaluate('document.activeElement===arguments[0]', amount.element_handle()), 'copy stole amount focus'

            for tab in ("services","promotions","contacts","tasks","visits","payment"):
                page.locator(f'[data-customer-tab="{tab}"]').click(); page.wait_for_timeout(60)
                assert page.locator(f'[data-customer-panel="{tab}"]').is_visible(),f"tab failed: {tab}"
                assert page.locator('[data-customer-panel]:visible').count()==1,f"multiple panels after {tab}"

            assert page.locator('[data-resize-col]').count()==4
            before=read_width(page,"number"); attr_before=read_width(page,"attr")
            handle=page.locator('[data-resize-col="number"]').first; box=handle.bounding_box()
            assert box and box["width"]>=16,"number resize handle too small"
            x,y=box["x"]+box["width"]/2,box["y"]+box["height"]/2
            page.mouse.move(x,y); page.mouse.down(); page.mouse.move(x+90,y,steps=8); page.mouse.up(); page.wait_for_timeout(600)
            after=read_width(page,"number"); assert after>=before+55,(before,after)
            near(read_width(page,"attr"),attr_before,3,"resizing number changed attr")
            page.reload(wait_until="networkidle"); near(read_width(page,"number"),after,3,"number width did not persist")
            page.goto(f"http://127.0.0.1:8123/customers/{cid2}",wait_until="networkidle")
            near(read_width(page,"number"),before,3,"width leaked to another customer")

            page.goto(f"http://127.0.0.1:8123/customers/{cid}?tab=services",wait_until="networkidle")
            page.evaluate("window.scrollTo(0,Math.max(0,Math.min(500,document.body.scrollHeight-innerHeight)))"); page.wait_for_timeout(80)
            y_before=page.evaluate("window.scrollY")
            service_edit=page.locator('[data-customer-panel="services"] [data-open-service-editor]').first
            service_edit.click(); page.locator('#businessAttributeDialog').wait_for(state="visible")
            near(page.evaluate("window.scrollY"),y_before,2,"opening editor moved page")
            cycle_row=page.locator('.global-attribute-row-v028[data-key="payment_interval_months"]'); assert cycle_row.count()==1
            cycle=cycle_row.locator('.attr-value'); assert cycle.get_attribute("type")=="text"; assert cycle.get_attribute("inputmode")=="numeric"
            old_cycle=cycle.input_value(); cycle.focus(); page.mouse.wheel(0,-600); page.wait_for_timeout(40)
            assert cycle.input_value()==old_cycle,"wheel changed payment interval"

            page.locator('[data-add-global-attribute]').click(); row=page.locator('.global-attribute-row-v028').last
            row.locator('.attr-label').fill("全局测试属性"); row.locator('.attr-value').fill("A值")
            page.locator('[data-business-attribute-form] button[type="submit"]').click(); page.locator('#businessAttributeDialog').wait_for(state="hidden")
            near(page.evaluate("window.scrollY"),y_before,3,"saving editor moved page")
            assert page.locator('.business-attribute').filter(has_text="全局测试属性").count()>=1
            assert page.locator('.business-attribute').filter(has_text="A值").count()>=1

            page.goto(f"http://127.0.0.1:8123/customers/{cid2}?tab=services",wait_until="networkidle")
            page.locator('[data-customer-panel="services"] [data-open-service-editor]').first.click()
            page.locator('#businessAttributeDialog').wait_for(state="visible")
            propagated=page.locator('.global-attribute-row-v028').evaluate_all("rows=>rows.filter(r=>r.querySelector('.attr-label')?.value==='全局测试属性').length")
            assert propagated==1,"global attribute did not propagate"
            page.locator('[data-business-editor-close]').first.click(); page.locator('#businessAttributeDialog').wait_for(state="hidden")

            page.goto(f"http://127.0.0.1:8123/customers/{cid}?tab=promotions",wait_until="networkidle")
            cols=page.locator('.promo-column-v028'); assert cols.count()==2
            left,right=cols.nth(0).bounding_box(),cols.nth(1).bounding_box()
            assert left and right and right["x"]>left["x"]+left["width"]*.65,"promotions not two columns"
            near(left["y"],right["y"],3,"promotion columns not aligned")
            heads=page.locator('.promo-column-head h3')
            assert heads.count()==2
            assert heads.nth(0).inner_text().strip()=="已经到期"
            assert heads.nth(1).inner_text().strip()=="即将到期"
            assert page.get_by_text("后续优惠不显示",exact=True).count()==0
            name_box=page.locator('.promo-name-copy-v028').first.bounding_box(); expiry_box=page.locator('.promo-expiry-input-v028').first.bounding_box()
            assert name_box and expiry_box; assert expiry_box["width"]<=150,expiry_box
            near(name_box["height"],expiry_box["height"],4,"promo name/expiry height mismatch")

            number_btn=page.locator('.promo-number-copy-v028').first; number=number_btn.get_attribute('data-copy-silent')
            number_btn.click(); page.wait_for_timeout(80); assert clipboard(page)==number
            assert page.locator('.app-toast').count()==0,"number copy showed toast"
            name_btn=page.locator('.promo-name-copy-v028').first; promo_name=name_btn.get_attribute('data-copy-silent')
            name_btn.click(); page.wait_for_timeout(80); assert clipboard(page)==promo_name
            assert page.locator('.app-toast').count()==0,"promo copy showed toast"

            page.goto("http://127.0.0.1:8123/?home=promos",wait_until="networkidle")
            assert page.locator('[data-home-panel="promos"]').is_visible(); home_rows=page.locator('.home-promo-customer')
            assert home_rows.count()==1,f"homepage promos not customer-grouped: {home_rows.count()}"; assert "UI测试客户A" in home_rows.first.inner_text()
            browser.close()

        assert not page_errors,"browser page errors: "+" | ".join(page_errors)
        assert not request_failures,"browser request failures: "+" | ".join(request_failures)
        print("UI acceptance passed")
    finally:
        server.terminate()
        try: server.wait(timeout=5)
        except subprocess.TimeoutExpired: server.kill()
        if server.returncode not in (0,-15):
            output=server.stdout.read() if server.stdout else ""; print(output,file=sys.stderr)


if __name__=="__main__": main()
