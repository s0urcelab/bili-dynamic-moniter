"""
task_state 表：worker 与 API 之间共享的任务状态。每个阶段一行。

    name                  阶段名
    enabled               开关；worker 每轮开始前、处理每个稿件前都会检查
    paused_reason         被自动暂停的原因（手动重新开启时清空）
    run_requested         API 请求立即执行，worker 轮询到后清除
    running               调度进程是否正在运行该阶段
    last_started_at / last_finished_at / last_status(ok|failed|timeout)
    last_summary          阶段本轮的处理摘要
    last_error / last_error_item / last_error_at   最近一次错误（跨轮保留，便于排查）
    error_in_run          本轮子进程是否已上报过错误
    consecutive_failures  连续失败的稿件数（目前用于上传的自动暂停）
"""
from datetime import datetime, timezone

from bdm import db

STAGES = ('fetch', 'download', 'upload', 'match')

STAGE_LABELS = {
    'fetch': '获取动态',
    'download': '下载视频',
    'upload': '上传云盘',
    'match': '识别BGM',
}

WORKER_HEARTBEAT_KEY = 'worker_heartbeat'

_FIELDS = {
    'enabled': 'bool',
    'paused_reason': 'text',
    'run_requested': 'bool',
    'running': 'bool',
    'last_started_at': 'time',
    'last_finished_at': 'time',
    'last_status': 'text',
    'last_summary': 'text',
    'last_error': 'text',
    'last_error_item': 'text',
    'last_error_at': 'time',
    'error_in_run': 'bool',
    'consecutive_failures': 'int',
    'updated_at': 'time',
}


def _now():
    return datetime.now(timezone.utc)


def _defaults(name):
    return {
        'name': name,
        'enabled': True,
        'paused_reason': None,
        'run_requested': False,
        'running': False,
        'last_started_at': None,
        'last_finished_at': None,
        'last_status': None,
        'last_summary': None,
        'last_error': None,
        'last_error_item': None,
        'last_error_at': None,
        'error_in_run': False,
        'consecutive_failures': 0,
    }


def _decode(row):
    return {'name': row['name'], **{k: db.decode(kind, row[k]) for k, kind in _FIELDS.items()}}


def _update(name, fields):
    cols = {k: db.encode(_FIELDS[k], v) for k, v in {**fields, 'updated_at': _now()}.items()}
    names = ', '.join(cols)
    assign = ', '.join(f'{c} = excluded.{c}' for c in cols)
    db.execute(f'INSERT INTO task_state (name, {names}) VALUES (?, {db.marks(cols)}) '
               f'ON CONFLICT (name) DO UPDATE SET {assign}', (name, *cols.values()))


def ensure_all():
    for name in STAGES:
        db.execute('INSERT INTO task_state (name) VALUES (?) ON CONFLICT (name) DO NOTHING', (name,))


def get(name):
    row = db.query_one('SELECT * FROM task_state WHERE name = ?', (name,))
    return _decode(row) if row else _defaults(name)


def all_states():
    rows = {r['name']: _decode(r) for r in db.query('SELECT * FROM task_state')}
    return [rows.get(n) or _defaults(n) for n in STAGES]


def is_enabled(name):
    return bool(get(name)['enabled'])


def set_enabled(name, enabled):
    fields = {'enabled': bool(enabled)}
    if enabled:
        fields.update({'paused_reason': None, 'consecutive_failures': 0})
    _update(name, fields)


def pause(name, reason):
    _update(name, {'enabled': False, 'paused_reason': reason})


def request_run(name):
    _update(name, {'run_requested': True})


def pop_run_requests():
    rows = db.query('UPDATE task_state SET run_requested = 0 WHERE run_requested = 1 RETURNING name')
    return [r['name'] for r in rows]


def mark_started(name):
    _update(name, {'running': True, 'last_started_at': _now(), 'last_summary': None, 'error_in_run': False})


def mark_finished(name, status, fallback_error=None):
    now = _now()
    _update(name, {'running': False, 'last_finished_at': now, 'last_status': status})
    if fallback_error:
        # 子进程本轮已上报更具体的错误时不覆盖
        db.execute('UPDATE task_state SET last_error = ?, last_error_item = NULL, last_error_at = ? '
                   'WHERE name = ? AND error_in_run = 0', (fallback_error, db.to_db_time(now), name))


def reset_running():
    db.execute('UPDATE task_state SET running = 0 WHERE running = 1')


def report_summary(name, summary):
    _update(name, {'last_summary': summary})


def report_error(name, error, item=None):
    _update(name, {
        'last_error': str(error)[:1000], 'last_error_item': item, 'last_error_at': _now(), 'error_in_run': True,
    })


def record_item_failure(name):
    return db.scalar(
        'INSERT INTO task_state (name, consecutive_failures) VALUES (?, 1) '
        'ON CONFLICT (name) DO UPDATE SET consecutive_failures = consecutive_failures + 1 '
        'RETURNING consecutive_failures', (name,),
    )


def reset_item_failures(name):
    _update(name, {'consecutive_failures': 0})


def heartbeat():
    db.set_setting(WORKER_HEARTBEAT_KEY, _now())


def last_heartbeat():
    return db.get_setting(WORKER_HEARTBEAT_KEY)
