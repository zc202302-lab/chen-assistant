"""Read-only public-site verification, separate from local CI and deployment.

Never logs in, reads private data, creates reminders or sends notifications.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://assistant.ziboxiaozhushou.cn'


def expected_version():
    for node in ast.parse((ROOT / 'app/config.py').read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'APP_VERSION' for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError('APP_VERSION not found')


def fetch(path):
    request = Request(BASE + path, headers={'User-Agent':'chen-assistant-production-check/1.0','Cache-Control':'no-cache'})
    with urlopen(request, timeout=12) as response:
        if urlsplit(response.url).netloc != urlsplit(BASE).netloc:
            raise RuntimeError('Unexpected cross-origin redirect')
        data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise RuntimeError('Unexpected oversized response')
        return response.url, response.headers, data


def verify():
    version = expected_version()
    _, _, raw = fetch('/health')
    health = json.loads(raw)
    if health.get('ok') is not True or health.get('version') != version:
        raise RuntimeError(f"Online version {health.get('version')!r}; expected {version}")
    _, _, raw = fetch('/manifest.webmanifest')
    manifest = json.loads(raw)
    if any(manifest.get(k) != v for k,v in {'id':'/','scope':'/','display':'standalone'}.items()):
        raise RuntimeError('PWA manifest is not current')
    for path in ['app/static/home-shortcuts.js','app/static/home-shortcuts.css','app/static/global-back.css','app/static/work-entry-layout.js','app/static/work-entry-layout.css','app/static/responsive-polish-v161.css','app/static/app.js','app/static/v028.js','app/static/live-refresh-modules-v15.js','app/static/quick-search-v15.js','app/static/quick-search-v15.css','app/static/work-sheet.js','app/static/work-sheet.css','app/static/work-architecture-v14.css','app/static/work-lists.css','app/static/sw.js','app/static/reminders.js','app/static/reminders.css','app/static/pwa-experience.js','app/static/pwa-experience.css','app/static/number-inbox-v162.css','app/static/number-inbox-v162.js','app/static/number-inbox-batch.css']:
        url = '/sw.js' if path.endswith('/sw.js') else '/' + path.removeprefix('app/')
        _, headers, raw = fetch(url)
        local = (ROOT / path).read_bytes()
        if hashlib.sha256(raw.strip()).digest() != hashlib.sha256(local.strip()).digest():
            raise RuntimeError(f'Online asset differs from validated source: {url}')
        if url == '/sw.js' and headers.get('Service-Worker-Allowed') != '/':
            raise RuntimeError('Service Worker does not control the root scope')
    for path in ['/reminders','/api/reminders','/work/number-inbox']:
        final, headers, _ = fetch(path)
        if urlsplit(final).path != '/login':
            raise RuntimeError(f'Unauthenticated reminder endpoint did not redirect to login: {path}')
        if path == '/work/number-inbox' and 'http://127.0.0.1:18764' not in headers.get('Content-Security-Policy', ''):
            raise RuntimeError('Online page CSP does not allow the signed number batch bridge')
    return f'ONLINE VERIFIED: v{version}; PWA manifest, exact work, list and push assets, root worker scope and authenticated reminder routes'


def main():
    last = ''
    for attempt in range(1,7):
        try:
            result = verify()
            print(result, flush=True)
            summary = os.environ.get('GITHUB_STEP_SUMMARY')
            if summary:
                with open(summary,'a',encoding='utf-8') as stream:
                    stream.write('### PWA production verification\n\n' + result + '\n')
            return 0
        except Exception as exc:
            # Only public health/asset errors; no credentials or private content.
            last = f'{type(exc).__name__}: {exc}'
            print(f'Online check {attempt}/6: {last}', flush=True)
            if attempt < 6:
                time.sleep(20)
    print('ONLINE NOT VERIFIED: ' + last, file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())

