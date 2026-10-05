"""Shared-folder updater. GitHub credentials stay on the online PC."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8', errors='backslashreplace')

REPO = 'zc202302-lab/chen-assistant'
BRANCH = 'feat/number-inbox-cloud-batch-export'
ALLOW = {'CloudMemberAddAgent.exe', 'version.json'}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def pending(bridge, install):
    try:
        manifest = json.loads((bridge / 'updates' / 'latest.json').read_text('utf-8'))
        version = json.loads((install / 'version.json').read_text('utf-8'))
        return manifest['version'] != version['version']
    except (OSError, ValueError, KeyError):
        return False

def apply_update(bridge, install):
    pointer = bridge / 'updates' / 'latest.json'
    if not pointer.exists():
        return False
    manifest = json.loads(pointer.read_text('utf-8'))
    version = manifest['version']
    if not isinstance(version, str) or len(version) != 40 or any(c not in '0123456789abcdef' for c in version):
        raise ValueError('更新版本格式错误')
    current = install / 'version.json'
    if current.exists() and json.loads(current.read_text('utf-8'))['version'] == version:
        return False
    package = bridge / 'updates' / (version + '.zip')
    if digest(package) != manifest['sha256']:
        raise ValueError('更新包尚未同步完整或校验失败')
    with tempfile.TemporaryDirectory(dir=install) as stage:
        stage = Path(stage)
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or not ALLOW.issubset(names):
                raise ValueError('更新包缺少文件或包含重复项')
            for name in ALLOW:
                (stage / name).write_bytes(archive.read(name))
        if json.loads((stage / 'version.json').read_text('utf-8'))['version'] != version:
            raise ValueError('更新包版本不一致')
        exe = install / 'CloudMemberAddAgent.exe'
        backup = install / 'CloudMemberAddAgent.previous.exe'
        if exe.exists():
            shutil.copy2(exe, backup)
        try:
            os.replace(stage / exe.name, exe)
            os.replace(stage / 'version.json', current)
        except Exception:
            if backup.exists():
                shutil.copy2(backup, exe)
            raise
    print('云电脑已更新：' + version[:12], flush=True)
    return True

def sync_once(bridge):
    # gh handles private-repository authentication on the online computer only.
    runs = json.loads(subprocess.check_output(['gh', 'run', 'list', '--repo', REPO,
        '--workflow', 'cloud-member-add-agent.yml', '--branch', BRANCH, '--status', 'success',
        '--limit', '1', '--json', 'databaseId,headSha'], text=True))
    if not runs:
        return
    run = runs[0]
    updates = bridge / 'updates'
    updates.mkdir(parents=True, exist_ok=True)
    pointer = updates / 'latest.json'
    if pointer.exists() and json.loads(pointer.read_text('utf-8'))['version'] == run['headSha']:
        return
    with tempfile.TemporaryDirectory() as stage:
        subprocess.run(['gh', 'run', 'download', str(run['databaseId']), '--repo', REPO,
            '--name', 'CloudMemberAddAgent', '--dir', stage], check=True)
        source = Path(stage) / 'CloudMemberAddAgent.zip'
        with zipfile.ZipFile(source) as archive:
            if json.loads(archive.read('version.json'))['version'] != run['headSha']:
                raise ValueError('构建版本不一致')
        target = updates / (run['headSha'] + '.zip')
        temporary = updates / (run['headSha'] + '.part')
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
        payload = {'version': run['headSha'], 'sha256': digest(target)}
        temporary_pointer = updates / 'latest.tmp'
        temporary_pointer.write_text(json.dumps(payload), 'utf-8')
        os.replace(temporary_pointer, pointer)
    print('本机已同步更新包：' + run['headSha'][:12], flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bridge', type=Path, default=Path(r'Y:\ChenBridge'))
    parser.add_argument('--sync', action='store_true')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    install = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    # Prevent two supervisors from starting agents against the same installation.
    if os.name == 'nt':
        import msvcrt
        lock = open(install / ('sync.lock' if args.sync else 'agent.lock'), 'a+b')
        lock.seek(0)
        lock.write(b'0')
        lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError('助手已在运行，请勿重复启动')
    while True:
        if args.sync:
            try:
                sync_once(args.bridge)
            except Exception as exc:
                print('本机同步暂未完成：' + str(exc), flush=True)
            if args.once:
                return
            time.sleep(60)
        else:
            update_ok = True
            try:
                apply_update(args.bridge, install)
            except Exception as exc:
                print('更新未完成，继续使用原版本：' + str(exc), flush=True)
                update_ok = False
            environment = dict(os.environ, CHEN_OFFLINE_UPDATE='1' if update_ok else '0')
            result = subprocess.run([str(install / 'CloudMemberAddAgent.exe'), '--bridge', str(args.bridge), '--port', '9222'], env=environment)
            if result.returncode != 75:
                return result.returncode
            time.sleep(2)

if __name__ == '__main__':
    try:
        sys.exit(main() or 0)
    except Exception as exc:
        print(str(exc), flush=True)
        sys.exit(1)
