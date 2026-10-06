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
from task_journal import atomic_json

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8', errors='backslashreplace')

REPO = 'zc202302-lab/chen-assistant'
CHANNELS = {'stable': 'main', 'development': 'feat/number-inbox-cloud-batch-export'}
BRANCH = CHANNELS['stable']
ALLOW = {'CloudMemberAddAgent.exe', 'version.json'}
SUPPORT_FILES = {'sync_updates.cmd', 'sync_updates.ps1', 'background_sync.ps1', 'diagnose_browser.cmd', 'README.md'}

def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()

def pending(bridge, install):
    try:
        manifest = json.loads((bridge / 'updates' / 'latest.json').read_text('utf-8'))
        version = json.loads((install / 'version.json').read_text('utf-8'))
        return manifest['version'] != version['version']
    except (OSError, ValueError, KeyError):
        return False

def _verify_agent(exe):
    if os.name == 'nt':
        subprocess.run([str(exe), '--self-check'], check=True, timeout=20,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def recover_update(install):
    marker = install / '.update-rollback.json'
    if not marker.exists():
        return
    record = json.loads(marker.read_text('utf-8'))
    allowed = ALLOW | SUPPORT_FILES | {'CloudOfflineUpdater.next.exe'}
    if not isinstance(record, dict) or any(name not in allowed or not isinstance(existed, bool) for name, existed in record.items()):
        raise ValueError('更新恢复记录无效，请保留原安装目录并人工检查')
    backup = install / '.update-backup'
    for name, existed in record.items():
        destination = install / name
        if existed:
            temp = install / (name + '.restore')
            shutil.copy2(backup / name, temp)
            os.replace(temp, destination)
        else:
            destination.unlink(missing_ok=True)
    marker.unlink()
    shutil.rmtree(backup)


def apply_update(bridge, install):
    recover_update(install)
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
    with tempfile.TemporaryDirectory(dir=install) as directory:
        stage = Path(directory)
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
            infos = archive.infolist()
            if (len(names) != len(set(names)) or len(names) > 64
                    or sum(i.file_size for i in infos) > 512 * 1024 * 1024
                    or not ALLOW.issubset(names)):
                raise ValueError('更新包缺少文件、重复或超过大小限制')
            meta = json.loads(archive.read('version.json'))
            if meta['version'] != version:
                raise ValueError('更新包版本不一致')
            if meta.get('protocol', 1) > 2:
                raise ValueError('更新协议过新，已保留原版本')
            if meta.get('protocol', 1) == 2 and not (SUPPORT_FILES | {'CloudOfflineUpdater.exe'}).issubset(names):
                raise ValueError('更新包缺少配套更新器或脚本')
            selected = ALLOW | (SUPPORT_FILES & set(names))
            for name in selected:
                (stage / name).write_bytes(archive.read(name))
            if 'CloudOfflineUpdater.exe' in names:
                (stage / 'CloudOfflineUpdater.next.exe').write_bytes(archive.read('CloudOfflineUpdater.exe'))
                selected.add('CloudOfflineUpdater.next.exe')
        backup = install / '.update-backup'
        shutil.rmtree(backup, ignore_errors=True)
        backup.mkdir()
        record = {}
        for name in selected:
            original = install / name
            record[name] = original.exists()
            if original.exists():
                shutil.copy2(original, backup / name)
        exe = install / 'CloudMemberAddAgent.exe'
        if exe.exists():
            shutil.copy2(exe, install / 'CloudMemberAddAgent.previous.exe')
        # A durable marker precedes all replacements. A crash rolls the entire set back.
        atomic_json(install / '.update-rollback.json', record)
        try:
            for name in sorted(selected - {'version.json'}):
                os.replace(stage / name, install / name)
            _verify_agent(exe)  # Import/self-check only; never connects to business browser.
            os.replace(stage / 'version.json', current)
            (install / '.update-rollback.json').unlink()
        except BaseException:
            recover_update(install)
            raise
        shutil.rmtree(backup, ignore_errors=True)
    print('云电脑已更新：' + version[:12], flush=True)
    return True

def sync_once(bridge, channel='stable'):
    if not bridge.is_dir():
        raise ValueError('共享文件夹不存在，请确认路径')
    branch = CHANNELS[channel]
    # gh handles private-repository authentication on the online computer only.
    runs = json.loads(subprocess.check_output(['gh', 'run', 'list', '--repo', REPO,
        '--workflow', 'cloud-member-add-agent.yml', '--branch', branch, '--status', 'success',
        '--limit', '1', '--json', 'databaseId,headSha'], text=True, timeout=60))
    if not runs:
        raise ValueError('该更新通道没有成功构建')
    run = runs[0]
    revision = run['headSha']
    if not isinstance(revision, str) or len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
        raise ValueError('构建提交格式错误')
    updates = bridge / 'updates'
    updates.mkdir(parents=True, exist_ok=True)
    pointer = updates / 'latest.json'
    if pointer.exists() and json.loads(pointer.read_text('utf-8'))['version'] == run['headSha']:
        print('共享目录已是最新版，本次检查结束。', flush=True)
        return
    with tempfile.TemporaryDirectory() as stage:
        subprocess.run(['gh', 'run', 'download', str(run['databaseId']), '--repo', REPO,
            '--name', 'CloudMemberAddAgent', '--dir', stage], check=True, timeout=300)
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
    parser.add_argument('--channel', choices=tuple(CHANNELS))
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args()
    if args.self_check:
        print('offline-updater self-check ok', flush=True)
        return 0
    install = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    channel = args.channel
    if channel is None:
        try:
            channel = json.loads((install / 'version.json').read_text('utf-8')).get('channel', 'stable')
        except (OSError, ValueError):
            channel = 'stable'
    if channel not in CHANNELS:
        raise ValueError('更新通道无效')
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
                sync_once(args.bridge, channel)
                if getattr(sys, 'frozen', False):
                    apply_update(args.bridge, install)
            except Exception as exc:
                print('本机同步暂未完成：' + str(exc), flush=True)
                return 1
            return 0  # Online PC updates are always manually triggered, once.
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
