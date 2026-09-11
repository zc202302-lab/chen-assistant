from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    # Browser acceptance tests must always use isolated data stores.
    acceptance_files = sorted((ROOT / 'tests').glob('v03*_acceptance.py'))
    assert acceptance_files, '未发现 v0.3 浏览器验收脚本'
    for path in acceptance_files:
        text = path.read_text(encoding='utf-8')
        assert 'APP_DB_PATH' in text, f'{path.name} 未配置隔离数据库'
        assert 'tempfile.TemporaryDirectory' in text, f'{path.name} 未使用临时目录'
        assert '.unlink()' not in text, f'{path.name} 仍包含删除数据库/文件操作'

    config = (ROOT / 'app' / 'config.py').read_text(encoding='utf-8')
    assert 'APP_DB_PATH' in config
    assert 'DB_PATH = Path(_db_override)' in config

    actions = (ROOT / 'app' / 'static' / 'v031_workflow_actions.js').read_text(encoding='utf-8')
    assert "FOXMAIL_BRIDGE = 'http://127.0.0.1:18763'" in actions
    assert 'payment-mail-compose-v031' in actions
    assert "bridgeFetch('/compose'" in actions
    assert 'result.verified !== true' in actions
    assert 'attachment_filename_b64' in actions
    assert 'attachment_content_base64' in actions

    patch_js = (ROOT / 'app' / 'static' / 'v033_payment_flow_patch.js').read_text(encoding='utf-8')
    assert 'window.confirm = message =>' in patch_js
    assert 'window.alert = message =>' in patch_js
    assert '确认缴费图片已经通过微信发送给客户' in patch_js
    assert '确认缴费邮件已经在Foxmail中发送给同事' in patch_js
    assert '确认同事已收到邮件，并且你已经完成本次实际支付' in patch_js
    assert '撤回“完成缴费”并恢复本次缴费前的周期状态' in patch_js
    assert '该客户已经发起缴费。修改金额后' in patch_js
    assert 'URL.createObjectURL(blob)' in patch_js
    assert 'download.download =' in patch_js
    assert 'Content-Disposition' in patch_js
    assert '缴费TXT已下载' in patch_js
    assert '未填写时只提示' in patch_js
    assert '不与其他客户共用' in patch_js
    assert '必填，不自动生成' in patch_js

    # Helper v0.5 may report HTTP 500 after a successful MAPI code-0 dispatch if
    # its secondary visible-window-count heuristic cannot see a new top-level
    # Foxmail window. Only that exact false-negative may be converted to an
    # accepted/pending state; real MAPI failures must still propagate.
    assert 'Foxmail MAPI returned success but no compose window was detected' in patch_js
    assert 'ChenFoxmailMapiAcceptedWindowUnverified' in patch_js
    assert "state: 'mapi-accepted-window-unverified'" in patch_js
    assert 'throw err;' in patch_js
    assert 'Foxmail已接收写信请求；请检查写信窗口和TXT附件' in patch_js

    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert '/static/v031_workflow_actions.js?v=0316' in base
    assert '/static/v031_workflow_runtime_fix.js?v=0314' in base
    assert '/static/v031_workflow_dom_guard.js?v=0314' in base
    assert '/static/v033_payment_flow_patch.js?v=0331' in base
    assert base.index('/static/v033_payment_flow_patch.js') > base.index('/static/v031_workflow_runtime_fix.js')

    # v0.3.3 attachment transport must be native Simple MAPI. The attachment is
    # part of the compose request itself; clipboard/SendKeys attachment injection
    # is explicitly forbidden because it can report success while Foxmail has no
    # attachment.
    helper = (ROOT / 'app' / 'static' / 'chen_foxmail_helper.ps1').read_text(encoding='utf-8')
    assert 'BridgeMode' in helper and 'TcpListener' in helper
    assert 'ComposeRequest' in helper and 'Invoke-FoxmailCompose' in helper
    assert 'Get-FoxmailMapiDll' in helper
    assert 'ChenFoxmailMapi' in helper
    assert 'MapiFileDesc' in helper
    assert 'MAPISendMail' in helper
    assert 'fileCount = 1' in helper
    assert 'files = filePtr' in helper
    assert 'pathName = attachmentPath' in helper
    assert 'fileName = attachmentName' in helper
    assert "mode = 'foxmail-direct-mapi'" in helper
    assert 'verified = $true' in helper
    assert 'verified_dispatch = $true' in helper
    assert "version = '0.5'" in helper
    assert "Path -eq '/compose'" in helper
    assert "AllowedRootDomain = 'ziboxiaozhushou.cn'" in helper
    assert 'Access-Control-Allow-Private-Network: true' in helper
    assert "SendWait('^v')" not in helper
    assert 'Clipboard]::SetFileDropList' not in helper
    assert 'Build-MailtoUri' not in helper

    # Server-side compose data must come from the customer-scoped v0.3.3 patch,
    # with no global recipient/default filename fallback.
    mail_patch = (ROOT / 'app' / 'v033_payment_flow_patch.py').read_text(encoding='utf-8')
    assert 'customer_mail_templates_v03' in mail_patch
    assert 'recipient TEXT NOT NULL' in mail_patch
    assert "'customer_scoped': True" in mail_patch
    assert "'attachment_required': True" in mail_patch
    assert 'attachment_content_base64' in mail_patch
    assert '当前客户缴费模板未填写' in mail_patch
    assert 'TXT附件文件名' in mail_patch
    assert 'RECIPIENT_META_KEY' not in mail_patch
    assert '_current_payment_txt_content' in mail_patch
    assert 'v03._payment_txt_content' not in mail_patch

    main_py = (ROOT / 'app' / 'main.py').read_text(encoding='utf-8')
    assert "connect-src 'self' http://127.0.0.1:18763 http://localhost:18763" in main_py
    assert "('.js', '.css', '.ps1')" in main_py
    assert '_assert_payment_flow_v033_guard' in main_py

    bootstrap = (ROOT / 'app' / 'static' / 'chen_foxmail_bootstrap.ps1').read_text(encoding='utf-8')
    assert 'UpdateIntervalMinutes = 30' in bootstrap
    assert 'chen_foxmail_helper.ps1' in bootstrap
    assert "Path -eq '/compose'" in bootstrap

    deploy = (ROOT / 'deploy.sh').read_text(encoding='utf-8')
    assert 'tests/v03_' not in deploy, '生产 deploy.sh 不得执行 v0.3 测试脚本'

    print('v0.3.3 safety/Foxmail native-attachment + MAPI false-negative compatibility + real-TXT-download contract passed')


if __name__ == '__main__':
    main()
