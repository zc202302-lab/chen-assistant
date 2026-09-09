from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    # Any v0.3 browser acceptance that starts the app or seeds data must opt into
    # an isolated APP_DB_PATH. This guards against ever repeating a production
    # deployment accidentally deleting data/app.db.
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

    js = (ROOT / 'app' / 'static' / 'v03_business_mail.js').read_text(encoding='utf-8')
    assert "FOXMAIL_BRIDGE = 'http://127.0.0.1:18763'" in js
    assert 'openWithLocalFoxmail' in js
    assert 'downloadBlob' in js
    assert '未检测到 Windows 助手' in js
    assert '/static/chen_foxmail_helper.ps1' in js
    assert "fd.append('recipient'" in js

    helper = (ROOT / 'app' / 'static' / 'chen_foxmail_helper.ps1').read_text(encoding='utf-8')
    assert 'BridgeMode' in helper and 'TcpListener' in helper
    assert "AllowedRootDomain = 'ziboxiaozhushou.cn'" in helper
    assert 'Access-Control-Allow-Private-Network: true' in helper
    assert 'Start-Process -FilePath $path' in helper
    assert 'Startup' in helper

    bridge = (ROOT / 'windows' / 'foxmail_bridge.ps1').read_text(encoding='utf-8')
    installer = (ROOT / 'windows' / 'install_foxmail_bridge.ps1').read_text(encoding='utf-8')
    assert 'IPAddress]::Loopback' in bridge or 'IPAddress]::IsLoopback' in bridge
    assert "AllowedRootDomain = 'ziboxiaozhushou.cn'" in bridge
    assert 'Access-Control-Allow-Private-Network: true' in bridge
    assert "Path -eq '/open'" in bridge
    assert '[IO.File]::WriteAllBytes' in bridge and 'Start-Process' in bridge
    assert 'Startup' in installer and 'foxmail_bridge.ps1' in installer

    mail_routes = (ROOT / 'app' / 'v03_mail_draft_routes.py').read_text(encoding='utf-8')
    assert "RECIPIENT_META_KEY = 'payment_mail_recipient_v03'" in mail_routes
    assert '_save_recipient' in mail_routes
    assert "recipient: str = Form('')" in mail_routes

    deploy = (ROOT / 'deploy.sh').read_text(encoding='utf-8')
    assert 'tests/v03_' not in deploy, '生产 deploy.sh 不得执行 v0.3 测试脚本'

    print('v0.3 safety/Foxmail contract passed')


if __name__ == '__main__':
    main()
