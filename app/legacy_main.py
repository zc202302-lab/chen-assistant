from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote
import calendar
import sqlite3

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config
from .db import init_db, db, now_iso
from .security import (
    configured, verify_login, create_session, get_session, delete_session,
    require_csrf, encrypt_secret, decrypt_secret
)

app = FastAPI(title='晨的助手 v0.1')
app.mount('/static', StaticFiles(directory=config.ROOT / 'app' / 'static'), name='static')
templates = Jinja2Templates(directory=config.ROOT / 'app' / 'templates')


@app.on_event('startup')
def startup():
    init_db()


def current_period():
    return date.today().strftime('%Y-%m')


def add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def cycle_months(text: str) -> int | None:
    s = (text or '').strip()
    if not s: return None
    if s in {'月','每月','1个月'}: return 1
    if s in {'季度','季','3个月'}: return 3
    if s in {'半年','6个月'}: return 6
    if s in {'年','每年','12个月'}: return 12
    if s.endswith('个月'):
        try: return int(s[:-2])
        except Exception: return None
    return None


def service_is_due(row, today: date | None = None) -> bool:
    today = today or date.today()
    months = cycle_months(row['payment_cycle'])
    if months is None: return False
    if months == 1: return True
    last = (row['last_payment_date'] or '').strip()
    if not last:
        return True
    try:
        last_d = date.fromisoformat(last[:10])
    except Exception:
        return True
    return add_months(last_d, months) <= today


def customer_is_due(conn: sqlite3.Connection, customer_id: int) -> bool:
    rows = conn.execute('SELECT payment_cycle,last_payment_date FROM services WHERE customer_id=?', (customer_id,)).fetchall()
    return any(service_is_due(r) for r in rows)


def effective_status(customer):
    same = customer['payment_period'] == current_period()
    return {
        'notified': int(customer['notified']) if same else 0,
        'completed': int(customer['completed']) if same else 0,
    }


def ctx(request: Request, **extra):
    session = getattr(request.state, 'session', None)
    base = {
        'request': request,
        'csrf': session['csrf_token'] if session else '',
        'app_username': config.APP_USERNAME,
        'today': date.today(),
    }
    base.update(extra)
    return base


@app.middleware('http')
async def auth_and_headers(request: Request, call_next):
    path = request.url.path
    public = path == '/login' or path.startswith('/static/') or path.startswith('/number-submit/') or path == '/api/number-inbox/pending' or path in {'/manifest.webmanifest','/sw.js','/health'}
    if not public:
        session = get_session(request.cookies.get('session_token'))
        if not session:
            return RedirectResponse('/login', status_code=303)
        request.state.session = session
    response = await call_next(request)
    if path == '/static/win-assistants/update.json':
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    elif path == '/static/win-assistants/win-assistants.exe':
        response.headers['Cache-Control'] = 'no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
    elif not path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    return response


@app.get('/health')
def health():
    return {'ok': True, 'version': '0.1'}


@app.get('/manifest.webmanifest')
def manifest():
    return FileResponse(config.ROOT / 'app' / 'static' / 'manifest.webmanifest', media_type='application/manifest+json')


@app.get('/sw.js')
def service_worker():
    return FileResponse(config.ROOT / 'app' / 'static' / 'sw.js', media_type='application/javascript', headers={'Service-Worker-Allowed':'/'})


@app.get('/login', response_class=HTMLResponse)
def login_page(request: Request, error: str = ''):
    return templates.TemplateResponse('login.html', {'request': request, 'error': error, 'configured': configured()})


@app.post('/login')
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if not configured():
        return RedirectResponse('/login?error=尚未运行setup_env.py', status_code=303)
    if not verify_login(username.strip(), password):
        return RedirectResponse('/login?error=用户名或密码错误', status_code=303)
    token, _, _ = create_session()
    resp = RedirectResponse('/', status_code=303)
    resp.set_cookie('session_token', token, max_age=30*86400, httponly=True, secure=config.APP_SECURE_COOKIE, samesite='strict', path='/')
    return resp


@app.post('/logout')
def logout(request: Request, csrf: str = Form(...)):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    token = request.cookies.get('session_token')
    delete_session(token)
    resp = RedirectResponse('/login', status_code=303)
    resp.delete_cookie('session_token', path='/')
    return resp


@app.get('/', response_class=HTMLResponse)
def dashboard(request: Request):
    today = date.today().isoformat()
    with db() as conn:
        tasks = conn.execute('''SELECT t.*, c.name customer_name FROM tasks t LEFT JOIN customers c ON c.id=t.customer_id
                                WHERE t.done=0 AND (t.remind_date='' OR t.remind_date<=?)
                                ORDER BY CASE WHEN t.remind_date='' THEN 1 ELSE 0 END, t.remind_date LIMIT 20''', (today,)).fetchall()
        customers = conn.execute('SELECT * FROM customers ORDER BY updated_at DESC').fetchall()
        wait_notice, wait_payment, done_payment = [], [], []
        for c in customers:
            if not c['payment_enabled'] or not customer_is_due(conn, c['id']):
                continue
            s = effective_status(c)
            item = {'id':c['id'],'name':c['name']}
            if s['completed']:
                done_payment.append(item)
            elif s['notified']:
                wait_payment.append(item)
            else:
                wait_notice.append(item)
        promo_rows = conn.execute('''SELECT p.*, s.number, s.service_type, c.id customer_id, c.name customer_name
             FROM promotions p JOIN services s ON s.id=p.service_id JOIN customers c ON c.id=s.customer_id
             WHERE s.service_type='成员' AND p.expiry_date<>'' AND p.expiry_date<=date(?, '+60 day')
             ORDER BY p.expiry_date LIMIT 30''', (today,)).fetchall()
        recent = conn.execute('SELECT id,name,group_code,tax_id FROM customers ORDER BY updated_at DESC LIMIT 6').fetchall()
        product_count = conn.execute("SELECT COUNT(DISTINCT service_type) n FROM services WHERE service_type<>''").fetchone()['n']
    return templates.TemplateResponse('dashboard.html', ctx(request, tasks=tasks, wait_notice=wait_notice, wait_payment=wait_payment,
        done_payment=done_payment, promotions=promo_rows, recent=recent, product_count=product_count))


@app.get('/search', response_class=HTMLResponse)
def global_search(request: Request, q: str = ''):
    q = q.strip(); customers=[]; accounts=[]
    if q:
        like=f'%{q}%'
        with db() as conn:
            customers=conn.execute('''SELECT DISTINCT c.id,c.name,c.group_code,c.tax_id FROM customers c
              LEFT JOIN services s ON s.customer_id=c.id LEFT JOIN contacts k ON k.customer_id=c.id
              WHERE c.name LIKE ? OR c.group_code LIKE ? OR c.tax_id LIKE ? OR s.number LIKE ? OR s.account LIKE ? OR s.holder_name LIKE ? OR k.name LIKE ?
              ORDER BY c.name LIMIT 50''',(like,like,like,like,like,like,like)).fetchall()
            accounts=conn.execute('''SELECT id,platform,url,username,email,tags FROM website_accounts
              WHERE platform LIKE ? OR url LIKE ? OR username LIKE ? OR email LIKE ? OR tags LIKE ? ORDER BY platform LIMIT 30''',(like,like,like,like,like)).fetchall()
    return templates.TemplateResponse('search.html', ctx(request, q=q, customers=customers, accounts=accounts))


@app.get('/customers', response_class=HTMLResponse)
def customers(request: Request, q: str = '', product: str = ''):
    with db() as conn:
        params=[]
        where=[]
        join=''
        if q.strip():
            like=f'%{q.strip()}%'; join='LEFT JOIN services s ON s.customer_id=c.id LEFT JOIN contacts k ON k.customer_id=c.id'
            where.append('(c.name LIKE ? OR c.group_code LIKE ? OR c.tax_id LIKE ? OR s.number LIKE ? OR s.account LIKE ? OR k.name LIKE ?)')
            params.extend([like]*6)
        if product.strip():
            join='LEFT JOIN services s ON s.customer_id=c.id LEFT JOIN contacts k ON k.customer_id=c.id'
            where.append('s.service_type=?'); params.append(product.strip())
        sql='''SELECT DISTINCT c.*, (SELECT COUNT(*) FROM services ss WHERE ss.customer_id=c.id) service_count,
               (SELECT COALESCE(SUM(monthly_fee),0) FROM services ss WHERE ss.customer_id=c.id) monthly_total
               FROM customers c '''+join
        if where: sql += ' WHERE ' + ' AND '.join(where)
        sql += ' ORDER BY c.name'
        rows=conn.execute(sql,params).fetchall()
        product_types=conn.execute("SELECT service_type, COUNT(DISTINCT customer_id) customers FROM services WHERE service_type<>'' GROUP BY service_type ORDER BY customers DESC, service_type").fetchall()
    return templates.TemplateResponse('customers.html', ctx(request, customers=rows, q=q, product=product, product_types=product_types))


@app.get('/customers/new', response_class=HTMLResponse)
def customer_new_page(request: Request):
    return templates.TemplateResponse('customer_form.html', ctx(request, customer=None))


@app.post('/customers/new')
def customer_new(request: Request, csrf: str=Form(...), name: str=Form(...), group_code: str=Form(''), tax_id: str=Form(''), relation_summary: str=Form('')):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    name=name.strip()
    if not name: raise HTTPException(400, '客户名称不能为空')
    now=now_iso()
    with db() as conn:
        cur=conn.execute('''INSERT INTO customers(name,group_code,tax_id,relation_summary,payment_period,created_at,updated_at)
                            VALUES(?,?,?,?,?,?,?)''',(name,group_code.strip(),tax_id.strip(),relation_summary.strip(),current_period(),now,now))
    return RedirectResponse(f'/customers/{cur.lastrowid}',303)


@app.get('/customers/{customer_id}', response_class=HTMLResponse)
def customer_detail(request: Request, customer_id: int):
    with db() as conn:
        c=conn.execute('SELECT * FROM customers WHERE id=?',(customer_id,)).fetchone()
        if not c: raise HTTPException(404)
        entities=conn.execute('SELECT * FROM customer_entities WHERE customer_id=? ORDER BY id',(customer_id,)).fetchall()
        contacts=conn.execute('SELECT * FROM contacts WHERE customer_id=? ORDER BY id',(customer_id,)).fetchall()
        services=conn.execute('SELECT * FROM services WHERE customer_id=? ORDER BY service_type,source_row,id',(customer_id,)).fetchall()
        groups=defaultdict(list)
        for s in services:
            promos=conn.execute('SELECT * FROM promotions WHERE service_id=? ORDER BY expiry_date',(s['id'],)).fetchall()
            groups[s['service_type']].append({'row':s,'promotions':promos})
        tasks=conn.execute('SELECT * FROM tasks WHERE customer_id=? ORDER BY done,remind_date,id DESC',(customer_id,)).fetchall()
        visits=conn.execute('SELECT * FROM visits WHERE customer_id=? ORDER BY visit_date DESC,id DESC',(customer_id,)).fetchall()
        total=conn.execute('SELECT COALESCE(SUM(monthly_fee),0) t FROM services WHERE customer_id=?',(customer_id,)).fetchone()['t']
        promo_count=conn.execute("""SELECT COUNT(*) n FROM promotions p JOIN services s ON s.id=p.service_id
             WHERE s.customer_id=? AND s.service_type='成员' AND p.expiry_date<>'' AND p.expiry_date<=date('now','+60 day')""",(customer_id,)).fetchone()['n']
        st=effective_status(c)
    return templates.TemplateResponse('customer_detail.html', ctx(request, customer=c, entities=entities, contacts=contacts,
      service_groups=dict(groups), tasks=tasks, visits=visits, monthly_total=total, promo_count=promo_count, payment_status=st))


@app.post('/customers/{customer_id}/edit')
def customer_edit(request: Request, customer_id: int, csrf: str=Form(...), name: str=Form(...), group_code: str=Form(''), tax_id: str=Form(''), relation_summary: str=Form(''),
                  payment_enabled: str=Form('0'), employee_own: str=Form(''), employee_share: str=Form(''), leased_own: str=Form(''), leased_other: str=Form(''), other_status: str=Form('')):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    with db() as conn:
        conn.execute('''UPDATE customers SET name=?,group_code=?,tax_id=?,relation_summary=?,payment_enabled=?,employee_own=?,employee_share=?,leased_own=?,leased_other=?,other_status=?,updated_at=? WHERE id=?''',
                     (name.strip(),group_code.strip(),tax_id.strip(),relation_summary.strip(),1 if payment_enabled=='1' else 0,
                      employee_own.strip(),employee_share.strip(),leased_own.strip(),leased_other.strip(),other_status.strip(),now_iso(),customer_id))
    return RedirectResponse(f'/customers/{customer_id}#overview',303)


@app.post('/customers/{customer_id}/contacts')
def contact_add(request: Request, customer_id: int, csrf: str=Form(...), kind: str=Form(''), name: str=Form(''), relationship: str=Form(''), phone: str=Form('')):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    with db() as conn:
        conn.execute('INSERT INTO contacts(customer_id,kind,name,relationship,phone) VALUES(?,?,?,?,?)',(customer_id,kind.strip(),name.strip(),relationship.strip(),phone.strip()))
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?',(now_iso(),customer_id))
    return RedirectResponse(f'/customers/{customer_id}#contacts',303)


@app.post('/contacts/{contact_id}/delete')
def contact_delete(request: Request, contact_id: int, csrf: str=Form(...)):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    with db() as conn:
        row=conn.execute('SELECT customer_id FROM contacts WHERE id=?',(contact_id,)).fetchone()
        if row: conn.execute('DELETE FROM contacts WHERE id=?',(contact_id,))
    return RedirectResponse(f"/customers/{row['customer_id']}#contacts" if row else '/customers',303)


@app.post('/customers/{customer_id}/services')
def service_add(request: Request, customer_id: int, csrf: str=Form(...), service_type: str=Form(...), holder_name: str=Form(''), number: str=Form(''), account: str=Form(''),
                monthly_fee: float=Form(0), fixed_fee: str=Form('0'), payment_cycle: str=Form(''), payment_method: str=Form(''), invoice_type: str=Form(''), package_type: str=Form(''), last_payment_date: str=Form('')):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    with db() as conn:
        conn.execute('''INSERT INTO services(customer_id,service_type,holder_name,number,account,monthly_fee,fixed_fee,payment_cycle,payment_method,invoice_type,package_type,last_payment_date)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(customer_id,service_type.strip(),holder_name.strip(),number.strip(),account.strip(),monthly_fee,1 if fixed_fee=='1' else 0,payment_cycle.strip(),payment_method.strip(),invoice_type.strip(),package_type.strip(),last_payment_date.strip()))
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?',(now_iso(),customer_id))
    return RedirectResponse(f'/customers/{customer_id}#services',303)


@app.post('/services/{service_id}/edit')
def service_edit(request: Request, service_id: int, csrf: str=Form(...), service_type: str=Form(...), holder_name: str=Form(''), number: str=Form(''), account: str=Form(''),
                 monthly_fee: float=Form(0), fixed_fee: str=Form('0'), payment_cycle: str=Form(''), payment_method: str=Form(''), invoice_type: str=Form(''), package_type: str=Form(''), last_payment_date: str=Form('')):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    with db() as conn:
        row=conn.execute('SELECT customer_id FROM services WHERE id=?',(service_id,)).fetchone()
        if not row: raise HTTPException(404)
        conn.execute('''UPDATE services SET service_type=?,holder_name=?,number=?,account=?,monthly_fee=?,fixed_fee=?,payment_cycle=?,payment_method=?,invoice_type=?,package_type=?,last_payment_date=? WHERE id=?''',
                     (service_type.strip(),holder_name.strip(),number.strip(),account.strip(),monthly_fee,1 if fixed_fee=='1' else 0,payment_cycle.strip(),payment_method.strip(),invoice_type.strip(),package_type.strip(),last_payment_date.strip(),service_id))
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?',(now_iso(),row['customer_id']))
    return RedirectResponse(f"/customers/{row['customer_id']}#services",303)


@app.post('/services/{service_id}/delete')
def service_delete(request: Request, service_id: int, csrf: str=Form(...)):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    with db() as conn:
        row=conn.execute('SELECT customer_id FROM services WHERE id=?',(service_id,)).fetchone()
        if row: conn.execute('DELETE FROM services WHERE id=?',(service_id,))
    return RedirectResponse(f"/customers/{row['customer_id']}#services" if row else '/customers',303)


@app.post('/services/{service_id}/promotions')
def promotion_add(request: Request, service_id: int, csrf: str=Form(...), name: str=Form(...), expiry_date: str=Form('')):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    with db() as conn:
        row=conn.execute('SELECT customer_id FROM services WHERE id=?',(service_id,)).fetchone()
        if not row: raise HTTPException(404)
        conn.execute('INSERT INTO promotions(service_id,name,expiry_date) VALUES(?,?,?)',(service_id,name.strip(),expiry_date.strip()))
    return RedirectResponse(f"/customers/{row['customer_id']}#services",303)


@app.post('/promotions/{promotion_id}/delete')
def promotion_delete(request: Request, promotion_id: int, csrf: str=Form(...)):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    with db() as conn:
        row=conn.execute('''SELECT s.customer_id FROM promotions p JOIN services s ON s.id=p.service_id WHERE p.id=?''',(promotion_id,)).fetchone()
        if row: conn.execute('DELETE FROM promotions WHERE id=?',(promotion_id,))
    return RedirectResponse(f"/customers/{row['customer_id']}#services" if row else '/customers',303)


@app.post('/customers/{customer_id}/tasks')
def task_add(request: Request, customer_id: int, csrf: str=Form(...), title: str=Form(...), remind_date: str=Form(''), note: str=Form('')):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    with db() as conn:
        conn.execute('INSERT INTO tasks(customer_id,title,remind_date,note,created_at) VALUES(?,?,?,?,?)',(customer_id,title.strip(),remind_date.strip(),note.strip(),now_iso()))
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?',(now_iso(),customer_id))
    return RedirectResponse(f'/customers/{customer_id}#tasks',303)


@app.post('/tasks/{task_id}/toggle')
def task_toggle(request: Request, task_id: int, csrf: str=Form(...)):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    with db() as conn:
        row=conn.execute('SELECT customer_id,done FROM tasks WHERE id=?',(task_id,)).fetchone()
        if row: conn.execute('UPDATE tasks SET done=? WHERE id=?',(0 if row['done'] else 1,task_id))
    return RedirectResponse(f"/customers/{row['customer_id']}#tasks" if row and row['customer_id'] else '/',303)


@app.post('/customers/{customer_id}/visits')
def visit_add(request: Request, customer_id: int, csrf: str=Form(...), visit_date: str=Form(''), kind: str=Form('拜访'), result: str=Form(''), plan: str=Form(''), create_task: str=Form('0'), task_date: str=Form('')):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    with db() as conn:
        conn.execute('INSERT INTO visits(customer_id,visit_date,kind,result,plan,created_at) VALUES(?,?,?,?,?,?)',(customer_id,visit_date.strip() or date.today().isoformat(),kind.strip(),result.strip(),plan.strip(),now_iso()))
        if create_task=='1' and plan.strip():
            conn.execute('INSERT INTO tasks(customer_id,title,remind_date,note,created_at) VALUES(?,?,?,?,?)',(customer_id,plan.strip(),task_date.strip(),'由跟进记录自动创建',now_iso()))
        conn.execute('UPDATE customers SET updated_at=? WHERE id=?',(now_iso(),customer_id))
    return RedirectResponse(f'/customers/{customer_id}#visits',303)


@app.post('/customers/{customer_id}/payment-status')
def payment_status(request: Request, customer_id: int, csrf: str=Form(...), action: str=Form(...)):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    with db() as conn:
        if action=='notify':
            conn.execute('UPDATE customers SET notified=1,completed=0,payment_period=?,updated_at=? WHERE id=?',(current_period(),now_iso(),customer_id))
        elif action=='complete':
            conn.execute('UPDATE customers SET notified=1,completed=1,payment_period=?,updated_at=? WHERE id=?',(current_period(),now_iso(),customer_id))
            # 非月缴业务确认完成时，把“上次缴费”推进到今天，避免下月继续误报
            rows=conn.execute('SELECT id,payment_cycle,last_payment_date FROM services WHERE customer_id=?',(customer_id,)).fetchall()
            for s in rows:
                m=cycle_months(s['payment_cycle'])
                if m and m>1:
                    conn.execute('UPDATE services SET last_payment_date=? WHERE id=?',(date.today().isoformat(),s['id']))
        elif action=='reset':
            conn.execute('UPDATE customers SET notified=0,completed=0,payment_period=?,updated_at=? WHERE id=?',(current_period(),now_iso(),customer_id))
        else:
            raise HTTPException(400)
    return RedirectResponse(f'/customers/{customer_id}#payment',303)


@app.get('/customers/{customer_id}/payment.txt')
def payment_txt(customer_id: int):
    with db() as conn:
        c=conn.execute('SELECT name FROM customers WHERE id=?',(customer_id,)).fetchone()
        if not c: raise HTTPException(404)
        rows=conn.execute("SELECT number,monthly_fee FROM services WHERE customer_id=? AND TRIM(number)<>'' AND monthly_fee IS NOT NULL ORDER BY source_row,id",(customer_id,)).fetchall()
    # 严格保持“号码 | 金额”数据行；无标题、无合计、无说明。
    lines=[]
    for r in rows:
        fee=float(r['monthly_fee'] or 0)
        fee_text=str(int(fee)) if fee.is_integer() else ('%.2f'%fee).rstrip('0').rstrip('.')
        lines.append(f"{r['number'].strip()} | {fee_text}")
    body='\r\n'.join(lines)
    safe=''.join(ch for ch in c['name'] if ch not in '\\/:*?"<>|') or '缴费'
    headers={'Content-Disposition': f"attachment; filename=\"payment.txt\"; filename*=UTF-8''{quote(safe + '.txt')}"}
    return PlainTextResponse(body, media_type='text/plain; charset=utf-8', headers=headers)


@app.get('/products', response_class=HTMLResponse)
def products(request: Request):
    with db() as conn:
        rows=conn.execute('''SELECT service_type,COUNT(*) service_count,COUNT(DISTINCT customer_id) customer_count,COALESCE(SUM(monthly_fee),0) monthly_total
                             FROM services WHERE service_type<>'' GROUP BY service_type ORDER BY customer_count DESC,service_count DESC''').fetchall()
    return templates.TemplateResponse('products.html', ctx(request, products=rows))


@app.get('/accounts', response_class=HTMLResponse)
def accounts(request: Request, q: str=''):
    with db() as conn:
        if q.strip():
            like=f'%{q.strip()}%'
            rows=conn.execute('''SELECT * FROM website_accounts WHERE platform LIKE ? OR url LIKE ? OR username LIKE ? OR email LIKE ? OR tags LIKE ? ORDER BY platform''',(like,like,like,like,like)).fetchall()
        else:
            rows=conn.execute('SELECT * FROM website_accounts ORDER BY platform').fetchall()
    return templates.TemplateResponse('accounts.html', ctx(request, accounts=rows, q=q))


@app.get('/accounts/new', response_class=HTMLResponse)
def account_new_page(request: Request):
    return templates.TemplateResponse('account_form.html', ctx(request, account=None))


@app.post('/accounts/new')
def account_new(request: Request, csrf: str=Form(...), platform: str=Form(...), url: str=Form(''), username: str=Form(''), email: str=Form(''), phone: str=Form(''), tags: str=Form(''), notes: str=Form(''), password: str=Form('')):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    now=now_iso()
    with db() as conn:
        cur=conn.execute('''INSERT INTO website_accounts(platform,url,username,email,phone,tags,notes,password_enc,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                         (platform.strip(),url.strip(),username.strip(),email.strip(),phone.strip(),tags.strip(),notes.strip(),encrypt_secret(password),now,now))
    return RedirectResponse(f'/accounts/{cur.lastrowid}',303)


@app.get('/accounts/{account_id}', response_class=HTMLResponse)
def account_detail(request: Request, account_id: int):
    with db() as conn:
        a=conn.execute('SELECT * FROM website_accounts WHERE id=?',(account_id,)).fetchone()
    if not a: raise HTTPException(404)
    return templates.TemplateResponse('account_detail.html', ctx(request, account=a))


@app.post('/accounts/{account_id}/edit')
def account_edit(request: Request, account_id: int, csrf: str=Form(...), platform: str=Form(...), url: str=Form(''), username: str=Form(''), email: str=Form(''), phone: str=Form(''), tags: str=Form(''), notes: str=Form(''), password: str=Form('')):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    with db() as conn:
        old=conn.execute('SELECT password_enc FROM website_accounts WHERE id=?',(account_id,)).fetchone()
        if not old: raise HTTPException(404)
        enc=encrypt_secret(password) if password else old['password_enc']
        conn.execute('''UPDATE website_accounts SET platform=?,url=?,username=?,email=?,phone=?,tags=?,notes=?,password_enc=?,updated_at=? WHERE id=?''',
                     (platform.strip(),url.strip(),username.strip(),email.strip(),phone.strip(),tags.strip(),notes.strip(),enc,now_iso(),account_id))
    return RedirectResponse(f'/accounts/{account_id}',303)


@app.post('/accounts/{account_id}/password')
def account_password(request: Request, account_id: int, csrf: str=Form(...)):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    with db() as conn:
        row=conn.execute('SELECT password_enc FROM website_accounts WHERE id=?',(account_id,)).fetchone()
    if not row: raise HTTPException(404)
    try: password=decrypt_secret(row['password_enc'])
    except Exception: raise HTTPException(500,'密码解密失败，请检查 APP_ENCRYPTION_KEY')
    return JSONResponse({'password':password})


@app.post('/accounts/{account_id}/delete')
def account_delete(request: Request, account_id: int, csrf: str=Form(...)):
    try: require_csrf(request.state.session, csrf)
    except ValueError: raise HTTPException(403)
    with db() as conn:
        conn.execute('DELETE FROM website_accounts WHERE id=?',(account_id,))
    return RedirectResponse('/accounts',303)
