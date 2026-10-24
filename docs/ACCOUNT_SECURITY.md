# 账户与邮箱找回

Web1.7.22为现有单一管理账户增加密码和邮箱管理，不开放注册或新增用户。

## 使用

侧边导航→账户与安全。验证当前密码可修改密码、申请绑定/更换找回邮箱或退出其他设备。邮箱收到8位验证码后，输入验证码并再次验证当前密码完成绑定；发送失败/验证码过期不会替换已有邮箱。已绑定邮箱默认不能由未登录者更改。

登录页→忘记密码，填写预先绑定且验证的邮箱。验证码10分钟有效，单次使用；输错5次后重新申请。发送间隔60秒，另有IP和账户每日配额。重置后不自动登录；原有所有设备的登录状态失效，使用新密码重新登录。找回请求统一提示，不披露邮箱是否绑定或邮件发送异常。

密码允许1～512个字符，不截断或自动去除空格，建议使用足够长的独立密码。密码保留原scrypt摘要机制，不保存明文。验证码只存HMAC摘要；后台发信，不在URL、响应或日志中返回验证码。账户设置、修改及绑定操作需要已登录CSRF；公开找回/重置表单使用签名、限时、SameSite严格Cookie的独立CSRF。

## 邮件配置

账户邮件默认复用服务器.env中的SMTP_HOST、SMTP_PORT、SMTP_USERNAME、SMTP_PASSWORD、SMTP_FROM、SMTP_USE_SSL、SMTP_STARTTLS；不复用PAYMENT_EMAIL_TO。也可以用ACCOUNT_前缀配置独立发件服务，例如：

```ini
ACCOUNT_SMTP_HOST=smtp.example.com
ACCOUNT_SMTP_PORT=465
ACCOUNT_SMTP_USERNAME=sender@example.com
ACCOUNT_SMTP_PASSWORD=在服务器填写邮箱SMTP授权码
ACCOUNT_SMTP_FROM=sender@example.com
ACCOUNT_SMTP_USE_SSL=1
ACCOUNT_SMTP_STARTTLS=0
```

支持SSL或STARTTLS，拒绝明文传输；不关闭证书校验。具体服务器、端口和授权码由邮箱提供方确定。不要将授权码发到聊天或提交GitHub。修改.env后执行`systemctl restart chen-assistant`生效；账户安全页会提示未配置。首次绑定、实际验证码接收必须由账户所有者在生产网页操作确认；自动验收仅使用隔离数据库和模拟SMTP，不向真实邮箱发送。

## 忘记当前密码且还未绑定邮箱

首次仍需通过青岛服务器SSH恢复一次：

```bash
cd /opt/chen-assistant
.venv/bin/python scripts/reset_account_password.py
```

脚本先备份现有数据库，再交互输入并更新登录密码，撤销原登录；不重写.env、不变更APP_ENCRYPTION_KEY或APP_SESSION_SECRET，不删除客户/业务或绑定邮箱，无需重启服务。密码管理启用后新凭据在SQLite的account_security表持久化，优先于.env的初始密码；因此今后不要仅改.env密码摘要，也不要重跑setup_env.py覆盖原密钥。没有数据库记录的新安装和旧安装继续使用.env凭据，首次网页或CLI改密后才转为数据库凭据。

原账户、业务数据及数据加密密钥均保持。备份和.env都应私密保存。真正丢失数据加密密钥无法通过重置登录密码恢复解密。
