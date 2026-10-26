from pathlib import Path
import sys
import os
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TEMP = tempfile.TemporaryDirectory()
os.environ['APP_DB_PATH'] = str(Path(_TEMP.name) / 'app.db')


def main():
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
    assert 'toast(`缴费${label}已下载`)' in patch_js
    assert "id: 'paymentExcelButton', label: 'EXCEL'" in patch_js
    assert "id: 'paymentTxtButton', label: 'TXT'" in patch_js
    assert 'TXT附件文件名和EXCEL附件文件名都只属于当前客户' not in patch_js
    assert '不与其他客户共用' not in patch_js
    assert 'TXT与EXCEL完全分离' not in patch_js
    assert "const customerId = root.dataset.customerId || '';" in patch_js
    assert '/customers/${customerId}/payment-mail-draft-v03' in patch_js
    assert '[data-v03-mail-recipient]' in patch_js
    assert '[data-v03-mail-attachment-filename]' in patch_js
    assert 'TXT附件文件名 <small>必填</small>' in patch_js

    # v1.2.2 primary path: complete RFC822 draft -> local helper /open -> Windows Shell.
    # Simple MAPI is retained only as fallback, removing window-count detection from
    # the normal operator path while preserving compatibility on broken .eml associations.
    assert 'payment-mail-draft-v03' in patch_js
    assert "`${bridge}/open`" in patch_js
    assert 'fallbackMapi' in patch_js
    assert "fallback: 'direct-mapi'" in patch_js
    assert '__v122StableMailLaunch' in patch_js
    assert "brand.href = '/'" in patch_js
    assert 'Foxmail MAPI returned success but no compose window was detected' in patch_js
    assert "state: 'mapi-accepted-window-unverified'" in patch_js
    assert 'throw err;' in patch_js

    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert '/static/v031_workflow_actions.js?v=1590' in base
    assert '/static/v031_workflow_runtime_fix.js?v=1642' in base
    # v1.4.3 updates the DOM guard while retaining the same legacy safety behavior;
    # keep the contract tied to the currently shipped cache-busted asset version.
    assert '/static/v031_workflow_dom_guard.js?v=0315' in base
    assert '/static/v033_payment_flow_patch.js?v=1591' in base
    assert base.index('/static/v033_payment_flow_patch.js') > base.index('/static/v031_workflow_runtime_fix.js')

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
    assert "Path -eq '/open'" in helper
    assert "AllowedRootDomain = 'ziboxiaozhushou.cn'" in helper
    assert 'Access-Control-Allow-Private-Network: true' in helper
    assert "SendWait('^v')" not in helper
    assert 'Clipboard]::SetFileDropList' not in helper
    assert 'Build-MailtoUri' not in helper

    mail_patch = (ROOT / 'app' / 'v033_payment_flow_patch.py').read_text(encoding='utf-8')
    assert 'customer_mail_templates_v03' in mail_patch
    assert 'recipient TEXT NOT NULL' in mail_patch
    assert "'customer_scoped': True" in mail_patch
    assert "'attachment_required': True" in mail_patch
    assert 'attachment_content_base64' in mail_patch
    assert '当前客户缴费模板未填写' in mail_patch
    assert 'TXT附件文件名' in mail_patch
    assert '_require_attachment_filename' in mail_patch
    assert "quote(filename)" in mail_patch
    assert "safe + '.txt'" not in mail_patch
    assert 'RECIPIENT_META_KEY' not in mail_patch
    assert '_current_payment_txt_content' in mail_patch
    assert 'v03._payment_txt_content' not in mail_patch

    main_py = (ROOT / 'app' / 'main.py').read_text(encoding='utf-8')
    assert "connect-src 'self' http://127.0.0.1:18763 http://localhost:18763" in main_py
    assert "('.js', '.css', '.ps1')" in main_py
    from app.main import app
    from app.routing import assert_route_owners
    assert_route_owners(app)

    bootstrap = (ROOT / 'app' / 'static' / 'chen_foxmail_bootstrap.ps1').read_text(encoding='utf-8')
    assert 'UpdateIntervalMinutes = 5' in bootstrap
    assert 'chen_foxmail_helper.ps1' in bootstrap
    assert "Path -eq '/compose'" in bootstrap

    deploy = (ROOT / 'deploy.sh').read_text(encoding='utf-8')
    assert 'tests/v03_' not in deploy, '生产 deploy.sh 不得执行 v0.3 测试脚本'

    print('payment safety contract passed: template TXT filename + EML primary launch + MAPI fallback + global brand home')


if __name__ == '__main__':
    main()

