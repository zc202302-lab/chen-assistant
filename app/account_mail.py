"""TLS-only account recovery mail, independent of payment recipients."""
import os
import smtplib
import ssl
from email.message import EmailMessage


def settings():
    def value(name, default=''):
        return os.getenv('ACCOUNT_' + name, os.getenv(name, default))
    use_ssl = value('SMTP_USE_SSL', '1') == '1'
    starttls = value('SMTP_STARTTLS', '0' if use_ssl else '1') == '1'
    username = value('SMTP_USERNAME').strip()
    try:
        port = int(value('SMTP_PORT', '465' if use_ssl else '587'))
    except ValueError:
        port = 0
    return {'host': value('SMTP_HOST').strip(), 'port': port, 'username': username,
            'password': value('SMTP_PASSWORD'), 'sender': value('SMTP_FROM', username).strip() or username,
            'ssl': use_ssl, 'starttls': starttls}


def available():
    s = settings()
    return bool(s['host'] and 0 < s['port'] < 65536 and s['sender']
                and (s['ssl'] or s['starttls']) and (not s['username'] or s['password']))


def send_code(email, code, purpose):
    if not available():
        raise RuntimeError('账户邮件发送未配置')
    s = settings()
    message = EmailMessage()
    message['From'] = s['sender']
    message['To'] = email
    action = '绑定找回邮箱' if purpose == 'bind' else '重置登录密码'
    message['Subject'] = '晨的小助手 · ' + action
    message.set_content(f'你正在{action}。\n\n验证码：{code}\n\n10分钟内有效，只能使用一次。请勿转发验证码。\n如果不是你本人操作，请忽略本邮件；账户密码不会因此改变。')
    context = ssl.create_default_context()
    if s['ssl']:
        with smtplib.SMTP_SSL(s['host'], s['port'], timeout=15, context=context) as smtp:
            if s['username']:
                smtp.login(s['username'], s['password'])
            smtp.send_message(message)
    else:
        with smtplib.SMTP(s['host'], s['port'], timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            if s['username']:
                smtp.login(s['username'], s['password'])
            smtp.send_message(message)
