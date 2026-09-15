from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    policy = (ROOT / 'docs' / 'development-compatibility-policy.md').read_text(encoding='utf-8')
    pr_template = (ROOT / '.github' / 'pull_request_template.md').read_text(encoding='utf-8')
    workflow = (ROOT / '.github' / 'workflows' / 'rebuild-check.yml').read_text(encoding='utf-8')
    base = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    back_js = (ROOT / 'app' / 'static' / 'global-back.js').read_text(encoding='utf-8')
    review_patch = (ROOT / 'app' / 'v031_fixed_review_patch.py').read_text(encoding='utf-8')

    for token in (
        '新增功能不能破坏已经确定的功能',
        '不得为了“变绿”而削弱旧测试',
        '未修改项不受影响',
        '真实交互测试',
    ):
        assert token in policy, token

    for token in (
        '已有功能兼容性审计（强制）',
        '完整历史 contract / regression / browser acceptance 已通过',
        'stability gate 已通过',
    ):
        assert token in pr_template, token

    # Existing stable suites must continue to be part of every feature PR. New
    # stable modules should be appended here when their acceptance test is added.
    required_suite_commands = (
        'python tests/stability_contract.py',
        'python tests/production_experience_regression.py',
        'python tests/v03_contract.py',
        'python tests/v031_payment_workflow_contract.py',
        'python tests/v032_customer_exchange_contract.py',
        'python tests/v12_recipe_tools_acceptance.py',
        'python tests/v10_workspace_isolation_acceptance.py',
        'python tests/v124_payment_search_acceptance.py',
        'python tests/v126_payment_workflow_rollback_acceptance.py',
        'python tests/v127_server_first_rollback_acceptance.py',
        'python tests/v13_customer_documents_acceptance.py',
        'python tests/v031_payment_workflow_acceptance.py',
        'python tests/v141_navigation_review_acceptance.py',
    )
    for command in required_suite_commands:
        assert command in workflow, f'missing compatibility suite command: {command}'

    # Global two-way navigation must remain present. v1.4.3 keeps an explicit
    # per-tab stack because native forward traversal proved unreliable in the real
    # cross-document browser acceptance. Guard both directions and the stateful
    # traversal contract here; the browser suite still verifies the actual clicks.
    assert 'data-history-back' in base
    assert 'data-history-forward' in base
    assert 'data-global-back' not in base
    assert 'data-back-fallback' not in base
    assert "STORAGE_KEY = 'chen-assistant:history-nav:v1432'" in back_js
    assert 'state.index > 0' in back_js
    assert 'state.index < state.entries.length - 1' in back_js
    assert 'navigateTo(state.index - 1)' in back_js
    assert 'navigateTo(state.index + 1)' in back_js
    assert 'state.pending = { target, index: targetIndex }' in back_js
    assert 'window.location.assign(target)' in back_js
    assert "MANUAL_UNCHECKED_SOURCE = 'manual_unchecked'" in review_patch
    assert 'MANUAL_PENDING_SOURCES' in review_patch
    assert 'workflow_invalidated' in review_patch

    print('compatibility audit contract passed: policy + stable-suite coverage + critical regression guards')


if __name__ == '__main__':
    main()
