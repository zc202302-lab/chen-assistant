# 晨的助手 v0.1.1

这是从现有 `客户管理.xlsm` 业务逻辑迁移出来的第一版个人 PWA。目标不是复刻 Excel，而是先把每天真正会用到的能力放到手机桌面上，并保留长期扩展空间。

## v0.1 已实现

### 客户管理
- 客户列表、搜索、新建、修改。
- 客户名称、集团编码、税号在客户详情首屏固定展示并一键复制。
- 一键“复制客户三要素”。
- 关联主体（适配一个 Sheet 中存在第二主体的情况）。
- 客情概述、结构化联系人；电话可直接拨打/复制。
- 业务台账：类型、姓名/使用人、号码、账号、月缴费、定额、缴费周期、付款方式、发票类型、套餐、上次缴费。
- 业务号码和业务账号一键复制。
- 一项业务可保存任意数量的优惠，不再受 Excel O:AZ 固定列限制。
- 成员优惠到期工作队列（保持原 VBA 的“成员”范围；当前展示已到期及未来 60 天内到期项目）。
- 待办事项与到期提醒。
- 跟进记录：日期、类型、结果、下一步；可把“下一步”同时创建为待办。
- 产品汇总：保留原 VBA“产品汇总”的核心意图，可点击产品反查客户。
- 缴费状态：待通知 → 已通知未缴费 → 本期完成；进入新月份后状态按新周期重新计算。
- 缴费 TXT：**只输出每条 `号码 | 金额` 数据行，不写标题、合计、说明或其他内容。**

### Excel 数据迁移
- 已提供 `import_excel.py`，直接读取 `.xlsm` 的 OOXML 数据，不依赖 Excel/LibreOffice。
- 当前随包的 `data/app.db` 已从本次 `客户管理.xlsm` 迁移：
  - 52 个客户/专项 Sheet
  - 734 项业务
  - 813 条优惠记录（其中部分无到期日期）
  - 15 个结构化联系人
  - 8 个关联主体
  - 现有待办/拜访记录按原表实际内容迁移
- 原始 Excel 不会被修改。

### 个人网址账号密码
- 平台、网址、用户名、邮箱、手机号、标签、备注。
- 密码不以明文保存到 SQLite；使用 Fernet 对称加密后落库。
- “显示/复制密码”需要已登录会话和 CSRF 校验。

> 安全边界：v0.1 的密码模块属于“服务器端加密保险箱”，不是 Bitwarden/1Password 那类零知识密码管理器。如果攻击者同时完全控制服务器和 `.env` 加密密钥，仍可解密密码。重要账户建议继续保留成熟密码管理器作为主存储，后续可升级为浏览器端加密。

### PWA
- iPhone Safari 可“添加到主屏幕”。
- 独立图标和 standalone 显示模式。
- Service Worker **只缓存静态文件**，不会离线缓存客户、账户、密码等私密动态页面。

## 项目结构

```text
chen-assistant-v0.1/
├── app/
│   ├── main.py          # Web 路由和核心工作流
│   ├── db.py            # SQLite 数据结构
│   ├── security.py      # 登录、会话、密码加密
│   ├── importer.py      # XLSM 数据迁移
│   ├── templates/       # 手机网页
│   └── static/          # CSS/JS/PWA 图标
├── data/
│   └── app.db           # 当前迁移后的本地数据库（被 .gitignore 排除）
├── deploy/
│   ├── chen-assistant.service
│   └── nginx.conf.example
├── import_excel.py
├── setup_env.py
├── requirements.txt
└── .gitignore
```

## 第一次运行（本地或服务器）

要求 Python 3.11+。

```bash
cd chen-assistant-v0.1
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python setup_env.py
```

`setup_env.py` 会让你输入登录用户名和密码，然后生成 `.env`。`.env` 包含登录密码哈希、会话密钥和账户密码加密密钥，**不要上传 GitHub**。

本地测试时，把 `.env` 中：

```text
APP_SECURE_COOKIE=0
```

然后运行：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8010
```

访问：`http://127.0.0.1:8010`

正式 HTTPS 部署时应改回：

```text
APP_SECURE_COOKIE=1
```

## 再次从 Excel 导入

> 默认会清空“客户相关表”后重新导入，但不会清空网址账户表。正式长期使用后，不要随意执行全量重新导入，以免覆盖网页中新产生的客户修改。后续版本会增加增量同步/导入预览。

```bash
python import_excel.py /路径/客户管理.xlsm
```

## GitHub 使用原则

这个目录已经准备好直接作为 Git 仓库，但：

- `.env` 不会提交。
- `data/*.db` 不会提交。
- 客户资料、网址账户、密码密文不应该上传 GitHub。
- GitHub 只保存代码和说明文档。

首次：

```bash
git init
git add .
git commit -m "晨的助手 v0.1"
```

再在 GitHub 创建私有仓库并关联远端即可。

## 阿里云部署建议

应用只监听 `127.0.0.1:8010`，公网由现有 Nginx 提供 HTTPS。参考 `deploy/nginx.conf.example` 和 `deploy/chen-assistant.service`。

建议域名：

```text
assistant.ziboxiaozhushou.cn
```

部署完成后，在 iPhone Safari 打开 HTTPS 地址：

1. 点击 Safari 底部“分享”。
2. 选择“添加到主屏幕”。
3. 名称保留“晨的助手”。
4. 以后从桌面图标启动。

## 备份

真正开始使用后，最重要的是：

```text
data/app.db
.env
```

二者需要分别安全备份。数据库包含客户资料和加密后的网址密码；`.env` 中有解密密钥，**不要把两者放在同一个公开位置**。

## v0.1 当前有意保留的简化

- 单用户，不做团队权限。
- 缴费状态仍以“客户周期”为主，后续可以升级成逐业务/逐账期的缴费记录。
- Excel 中的部分专项 Sheet（如“单独企宽”“员工优惠套餐”“医保专线”）目前按客户型页面忠实导入，后续可根据实际使用改造成专项清单。
- 暂不做 AI、语音录入、附件、地图、复杂报表。


## v0.1.1 新增

详见 `UPDATE-v0.1.1.md`：开票分组、月度实际缴费金额记录、BOSS 查询录入工作台，以及客户详情布局优化。
