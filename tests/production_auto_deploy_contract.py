from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    deploy = (ROOT / 'deploy.sh').read_text(encoding='utf-8')
    workflow = (ROOT / '.github' / 'workflows' / 'rebuild-check.yml').read_text(encoding='utf-8')

    assert 'TARGET_REV="${CHEN_DEPLOY_TARGET_REV:-}"' in deploy
    assert 'git merge-base --is-ancestor "$TARGET_REV" origin/main' in deploy
    assert 'git merge --ff-only "$TARGET_REV"' in deploy
    assert 'CHEN_DEPLOY_TARGET_REV="$TARGET_REV"' in deploy
    assert 'git reset --hard' not in deploy
    assert '跳过过时部署任务且不回退' in deploy

    assert 'production_deploy_preflight:' in workflow
    assert 'deploy_stability:' in workflow
    assert 'deploy_production:' in workflow
    assert 'needs: [validate, deploy_stability]' in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in workflow
    assert 'group: chen-assistant-production' in workflow
    assert 'cancel-in-progress: false' in workflow
    assert 'app/*|storage_node/*|requirements.txt|deploy.sh' in workflow
    assert 'CHEN_DEPLOY_TARGET_REV=' in workflow
    for secret in ('PROD_HOST', 'PROD_USER', 'PROD_SSH_KEY', 'PROD_KNOWN_HOSTS'):
        assert f'secrets.{secret}' in workflow
    assert 'StrictHostKeyChecking=yes' in workflow
    assert 'LOCAL_DEPLOY_PRIVILEGE=' in workflow
    assert 'systemctl cat chen-assistant' in workflow
    assert 'falling back to remote SSH mode' in workflow
    assert 'bash "$GITHUB_WORKSPACE/deploy.sh"' in workflow
    assert '< "$GITHUB_WORKSPACE/deploy.sh"' in workflow
    assert 'Only non-Web files changed; production deployment is skipped.' in workflow

    print('automatic production deployment contract passed')


if __name__ == '__main__':
    main()
