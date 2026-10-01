# PWA 与统一提醒中心（1.7.0）

## 手机使用

在现有主站 Safari 中选择“分享 → 添加到主屏幕”，然后从主屏幕图标进入“提醒”，点击“开启手机提醒”并允许系统通知。iPhone 要求 iOS 16.4 或更高版本。点击“发送测试提醒”，关闭网页后确认锁屏或通知中心收到提醒。系统专注模式和通知设置会影响展示。

保持主站域名与现有业务路由不变；收集号码的独立分享域名不承载私人提醒中心。每个设备和网站来源的订阅独立，切换域名需要重新订阅。

## 当前接入与扩展

- 未加号码：按提交批次产生提醒，不在锁屏显示号码。初始化时跳过历史提交，避免旧号码集中推送。
- 客户待办：使用已有 `tasks.remind_at` / `remind_date`。无时区的时间按北京时间；只填写日期时在当天 09:00 到期。完成、删除或修改提醒时间后取消旧提醒的待发送队列。
- 客户、清单、Windows Assistant、系统类型已有统一开关和事件接口；未来模块按自己的业务触发条件调用，不自动为没有提醒规格的现有模块添加新触发规则。
- 支持站内记录、未读数量和 Badging API；不支持角标的浏览器自动忽略角标。

后端模块在自己的事务内调用：

```python
from app.reminders import publish_reminder
publish_reminder(conn, kind='work_list', title='清单需要处理',
    body='请查看欠费清单', url='/work/lists/123',
    event_key='work-list:123:record:456:revision:2')
```

事件标识必须稳定、全局唯一。重复提交同一标识不会重复生成提醒或发送队列。`task:` 和 `number-batch:` 前缀供现有采集器使用，新增模块应使用自己的前缀。

已登录客户端可 POST `/api/reminders/events`，JSON 为上述相同字段，附 `X-CSRF-Token`。未来 Windows 客户端需要经已有身份/设备认证体系接入该事件总线；此版本不添加公开或无认证的事件发送入口。

## 运维与交付

按现有 main 分支自动更新机制部署；`requirements.txt` 的变更会自动安装 `pywebpush`。部署脚本检查新提醒路由与数据库结构。FastAPI 启动时创建后台采集与发送任务，约每 15 秒处理一次，不依赖前台网页、浏览器轮询或浏览器定时器。

VAPID 密钥首次启动自动生成，私钥和订阅密钥使用现有 APP_ENCRYPTION_KEY 加密后保存在备份覆盖的 app.db 中，重启和部署不会换钥。无需新增必填环境变量或提交私钥。可通过 `WEB_PUSH_SUBJECT` 设置联系 URI；默认使用 APP_BASE_URL，再回退到现有主站 HTTPS URI。

推送初始化异常不会阻止原有网页版启动；提醒 API 返回 503 并显示配置错误，不降级保存明文密钥。部署预检仍验证提醒结构，后台错误会写入服务日志。

服务器需要能通过 HTTPS 访问 Apple、FCM 或 Mozilla 的推送服务。采用持久化 outbox、数据库租约、指数退避，最多尝试 8 次；404/410 自动停用过期订阅。发送结果或错误可在提醒中心设备区和 `/api/reminders` 的 delivery 汇总查看。推送服务接受请求与手机最终展示是两个阶段，真实手机验收仍须用户授权订阅后完成。

关闭总开关、类型开关或某台设备时，跳过其待发送队列；再次开启不会补发全部历史提醒。读取或处理提醒时取消尚未发送的对应通知。通知点击通过 `/reminders/open/{id}` 标记已读后跳到对应功能；登录过期时保留目标路径。

Service Worker 只缓存图标、Manifest 与通用离线提示。私有业务页面、接口和客户资料不缓存，现有网页版保持网络最新。失去网络时显示通用离线页面。

## 验证

```bash
python tests/reminders_push_contract.py
node tests/reminders_service_worker_contract.cjs
python tests/v162_number_inbox_contract.py
python tests/v164_task_review_contract.py
python tests/work_lists_contract.py
python tests/work_list_import_contract.py
python tests/production_auto_deploy_contract.py
```

后端测试使用隔离 SQLite 和模拟 HTTP 传输，真实运行 pywebpush 的 VAPID 签名及 AES128GCM 加密，不向真实手机或生产服务发送测试请求。新增测试已加入现有 CI。真机验收：开启 → 测试通知 → 关闭页面 → 锁屏收到通知 → 点击进入提醒中心；再通过同事链接提交号码，验证号码通知进入未加号码页面。
