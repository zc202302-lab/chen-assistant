"""Layered owner security settings and public, email-only password recovery."""
import hmac
import secrets
import time

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute

from . import account_security as service, config
from .account_mail import available
from .db import db
from .security import require_csrf, token_digest
from .templating import Jinja2Templates


class AccountFormRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request):
            if request.method != 'POST':
                return await handler(request)
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 16 * 1024:
                    raise HTTPException(413, '提交内容过大')
                body.extend(chunk)
            consumed = False

            async def receive():
                nonlocal consumed
                if consumed:
                    return {'type': 'http.disconnect'}
                consumed = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await handler(Request(request.scope, receive))
        return bounded


router = APIRouter(route_class=AccountFormRoute)
templates = Jinja2Templates(directory=config.ROOT / 'app/templates')
GENERIC = '如该邮箱已绑定且发送条件满足，验证码将发送至邮箱。请检查收件箱及垃圾邮件，60秒后可重试。'


def identity(request):
    return request.client.host if request.client else 'unknown'


def _csrf(request, value):
    try:
        require_csrf(getattr(request.state, 'session', None), value)
    except ValueError:
        raise HTTPException(403, 'CSRF校验失败')


def _public_csrf(request, value):
    cookie = request.cookies.get('account_recovery_csrf', '')
    try:
        stamp, nonce, signature = value.split('.')
        valid = (0 <= time.time() - int(stamp) < 1800 and len(nonce) == 32
                 and hmac.compare_digest(cookie, value)
                 and hmac.compare_digest(signature, token_digest('recovery-csrf:' + stamp + '.' + nonce)))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise HTTPException(403, '页面已过期，请刷新后重试。')


def public_page(request, page, message='', error='', status=200):
    stamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    value = stamp + '.' + nonce
    value += '.' + token_digest('recovery-csrf:' + value)
    response = templates.TemplateResponse('account_recovery.html', {'request': request,
        'page': page, 'csrf': value, 'message': message, 'error': error}, status_code=status)
    response.set_cookie('account_recovery_csrf', value, max_age=1800, httponly=True,
                        secure=config.APP_SECURE_COOKIE, samesite='strict', path='/account')
    return response


def settings_page(request, message='', error='', status=200):
    with db() as conn:
        record = service.account(conn)
        pending = conn.execute("SELECT email,state,expires FROM account_email_challenges WHERE purpose='bind'").fetchone()
        events = conn.execute('SELECT kind,occurred FROM account_security_events ORDER BY id DESC LIMIT 8').fetchall()
    return templates.TemplateResponse('account_security.html', {'request': request,
        'csrf': request.state.session['csrf_token'], 'username': config.APP_USERNAME,
        'email': record['recovery_email'], 'mail_available': available(),
        'pending': dict(pending) if pending and pending['expires'] > time.time() else None,
        'events': events, 'message': message, 'error': error}, status_code=status)


@router.get('/account/security', response_class=HTMLResponse)
def account_settings(request: Request):
    return settings_page(request)


@router.post('/account/password', response_class=HTMLResponse)
def account_password_change(request: Request, csrf: str = Form(''), current: str = Form(''),
                            password: str = Form(''), confirmation: str = Form('')):
    _csrf(request, csrf)
    try:
        if not service.change_password(current, password, confirmation, identity(request)):
            return settings_page(request, error='当前密码不正确或尝试过于频繁。', status=400)
    except ValueError as exc:
        return settings_page(request, error=str(exc), status=400)
    response = RedirectResponse('/login?notice=password-updated', status_code=303)
    response.delete_cookie('session_token', path='/')
    return response


@router.post('/account/email/request', response_class=HTMLResponse)
def account_email_request(request: Request, background_tasks: BackgroundTasks, csrf: str = Form(''),
                           current: str = Form(''), email: str = Form('')):
    _csrf(request, csrf)
    if not available():
        return settings_page(request, error='服务器尚未配置账户邮件发送，请按账户安全文档配置 SMTP。', status=400)
    try:
        challenge = service.prepare_challenge('bind', email, identity(request), current)
    except ValueError as exc:
        return settings_page(request, error=str(exc), status=400)
    if challenge is False:
        return settings_page(request, error='当前密码不正确或尝试过于频繁。', status=400)
    if challenge:
        background_tasks.add_task(service.deliver_challenge, *challenge)
    return settings_page(request, message='已申请发送绑定验证码。请查收邮件；10分钟内有效，60秒内请勿重复申请。')


@router.post('/account/email/confirm', response_class=HTMLResponse)
def account_email_confirm(request: Request, csrf: str = Form(''), current: str = Form(''),
                           email: str = Form(''), code: str = Form('')):
    _csrf(request, csrf)
    try:
        if not service.bind_email(current, email, code, identity(request)):
            return settings_page(request, error='验证未通过：请检查当前密码及邮箱验证码，或重新申请验证码。', status=400)
    except ValueError as exc:
        return settings_page(request, error=str(exc), status=400)
    return settings_page(request, message='找回邮箱已验证并绑定。')


@router.post('/account/sessions/revoke', response_class=HTMLResponse)
def account_sessions_revoke(request: Request, csrf: str = Form(''), current: str = Form('')):
    _csrf(request, csrf)
    if not service.revoke_other_sessions(current, identity(request), request.cookies.get('session_token', '')):
        return settings_page(request, error='当前密码不正确或尝试过于频繁。', status=400)
    return settings_page(request, message='其他设备已退出登录。')


@router.get('/account/forgot', response_class=HTMLResponse)
def account_forgot_page(request: Request):
    return public_page(request, 'forgot')


@router.post('/account/forgot', response_class=HTMLResponse)
def account_forgot(request: Request, background_tasks: BackgroundTasks, csrf: str = Form(''), email: str = Form('')):
    _public_csrf(request, csrf)
    try:
        challenge = service.prepare_challenge('reset', email, identity(request))
    except ValueError:
        challenge = None
    if challenge:
        background_tasks.add_task(service.deliver_challenge, *challenge)
    return public_page(request, 'reset', message=GENERIC)


@router.get('/account/reset', response_class=HTMLResponse)
def account_reset_page(request: Request):
    return public_page(request, 'reset')


@router.post('/account/reset', response_class=HTMLResponse)
def account_reset(request: Request, csrf: str = Form(''), email: str = Form(''), code: str = Form(''),
                    password: str = Form(''), confirmation: str = Form('')):
    _public_csrf(request, csrf)
    try:
        if not service.reset_password(email, code, password, confirmation, identity(request)):
            return public_page(request, 'reset', error='验证码无效、已过期或尝试次数已用完，请重新申请。', status=400)
    except ValueError as exc:
        return public_page(request, 'reset', error=str(exc), status=400)
    response = RedirectResponse('/login?notice=password-updated', status_code=303)
    response.delete_cookie('session_token', path='/')
    response.delete_cookie('account_recovery_csrf', path='/account')
    return response
