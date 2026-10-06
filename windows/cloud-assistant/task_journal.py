"""Durable per-row evidence. Interrupted rows are never submitted automatically."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


@contextmanager
def batch_lock(directory, payload):
    """Non-blocking lock on a stable file, held for the entire local batch."""
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(payload).hexdigest()
    with (directory / (key + '.lock')).open('a+b') as stream:
        if not stream.tell():
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield directory / (key + '.json')
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class BatchJournal:
    def __init__(self, path, payload, tasks):
        self.path = path
        self.tasks = tasks
        self.recovered = path.exists()
        fingerprint = hashlib.sha256(payload).hexdigest()
        rows = [{'row': t.row_number, 'service_number': t.service_number,
                 'group_search': t.group_search, 'status': '未执行', 'detail': ''}
                for t in tasks]
        if self.recovered:
            self.data = json.loads(path.read_text('utf-8'))
            if (self.data.get('version') != 1 or self.data.get('fingerprint') != fingerprint
                    or not isinstance(self.data.get('rows'), list)
                    or len(self.data['rows']) != len(rows)):
                raise ValueError('任务恢复记录无效；中转表已保留，请人工检查，禁止自动重试')
            for previous, expected in zip(self.data['rows'], rows):
                if (not isinstance(previous, dict)
                        or any(previous.get(k) != expected[k] for k in ('row', 'service_number', 'group_search'))
                        or previous.get('status') not in {'未执行', '执行中', '已添加', '已存在，跳过', '失败，已暂停', '结果待人工核对'}):
                    raise ValueError('任务恢复记录不匹配；禁止自动重试')
        else:
            self.data = {'version': 1, 'fingerprint': fingerprint, 'rows': rows}
            self.save()

    def save(self):
        atomic_json(self.path, self.data)

    def begin(self, index):
        self.data['rows'][index].update(status='执行中', detail='已开始执行；中断后必须人工核对')
        self.save()  # Must succeed before any browser operation.

    def finish(self, index, status, detail):
        self.data['rows'][index].update(status=status, detail=detail)
        self.save()

    def recovered_outcomes(self):
        for row in self.data['rows']:
            if row['status'] == '执行中':
                row.update(status='结果待人工核对', detail='上次执行中断，提交状态未知；未重新执行，请人工核对')
            elif row['status'] == '未执行':
                row['detail'] = '上次批次中断，已暂停；未自动继续或重试'
        self.save()
        return self.data['rows']
