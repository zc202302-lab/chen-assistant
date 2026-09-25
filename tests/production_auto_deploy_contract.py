from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    deploy = (ROOT / 'deploy.sh').read_text(encoding='utf-8')
    workflow = (ROOT / '.github' / 'workflows' / 'rebuild-check.yml').read_text(encoding='utf-8')
    worker = (ROOT / 'scripts' / 'auto_deploy_main.sh').read_text(encoding='utf-8')
    installer = (ROOT / 'scripts' / 'install_auto_deploy_timer.sh').read_text(encoding='utf-8')
    bootstrap = (ROOT / 'scripts' / 'bootstrap_production_auto_deploy.sh').read_text(encoding='utf-8')

    for script in (
        ROOT / 'deploy.sh',
        ROOT / 'scripts' / 'auto_deploy_main.sh',
        ROOT / 'scripts' / 'install_auto_deploy_timer.sh',
        ROOT / 'scripts' / 'bootstrap_production_auto_deploy.sh',
    ):
        subprocess.run(['bash', '-n', str(script)], check=True)

    assert 'TARGET_REV="${CHEN_DEPLOY_TARGET_REV:-}"' in deploy
    assert 'git merge-base --is-ancestor "$TARGET_REV" origin/main' in deploy
    assert 'git merge --ff-only "$TARGET_REV"' in deploy
    assert '跳过过时部署任务且不回退' in deploy
    assert 'git reset --hard' not in deploy
    assert 'timeout 60s git fetch origin main' in deploy
    assert 'last-successful-revision' in deploy
    assert 'deployment-status.json' in deploy
    assert '"revision": sys.argv[1]' in deploy
    assert 'CHEN_AUTO_DEPLOY_SYNC_ONLY=1' in deploy

    assert 'production_deploy_preflight:' in workflow
    assert 'deploy_stability:' in workflow
    assert 'deploy_production:' in workflow
    assert 'needs: [validate, deploy_stability]' in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert 'group: chen-assistant-production' in workflow
    assert 'cancel-in-progress: false' in workflow
    assert 'contents: write' in workflow
    assert 'Publish validated production revision' in workflow
    assert 'refs/heads/production-ready' in workflow
    assert 'app/*|storage_node/*|requirements.txt|deploy.sh|scripts/auto_deploy_main.sh' in workflow
    assert 'CHEN_DEPLOY_TARGET_REV=' in workflow
    assert 'systemctl cat chen-assistant' in workflow
    assert 'StrictHostKeyChecking=yes' in workflow
    for secret in ('PROD_HOST', 'PROD_USER', 'PROD_SSH_KEY', 'PROD_KNOWN_HOSTS'):
        assert f'secrets.{secret}' in workflow
    assert 'GitHub will wait for the production revision marker before reporting success.' in workflow
    assert 'Verify production reached exact revision' in workflow
    assert 'deployment-status.json' in workflow
    assert 'Production did not confirm exact revision' in workflow
    assert 'No Web runtime files changed; production deployment skipped.' in workflow

    assert 'CHEN_ASSISTANT_BRANCH:-production-ready' in worker
    assert 'flock -n 9' in worker
    assert 'timeout 60s git fetch' in worker
    assert 'for attempt in 1 2 3' in worker
    assert 'last-successful-revision' in worker
    assert 'FORCE_DEPLOY=1' in worker
    assert 'CHEN_DEPLOY_FROM_REV="$DIFF_BASE"' in worker
    assert 'automatic production deployment verified' in worker
    assert 'auto-deploy worker refreshed from validated production-ready revision' in worker

    assert 'CHEN_AUTO_DEPLOY_SYNC_ONLY' in installer
    assert 'Environment=CHEN_ASSISTANT_BRANCH=production-ready' in installer
    assert 'TimeoutStartSec=15min' in installer
    assert 'OnUnitInactiveSec=2min' in installer
    assert 'OnUnitActiveSec=2min' not in installer
    assert 'systemctl enable chen-assistant-auto-deploy.timer' in installer

    assert 'CHEN_DEPLOY_TARGET_REV="$TARGET_REV"' in bootstrap
    print('automatic production deployment resilience contract passed')


if __name__ == '__main__':
    main()
