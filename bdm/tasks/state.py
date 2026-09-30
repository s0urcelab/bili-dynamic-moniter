"""
task_state 集合：worker 与 API 之间共享的任务状态。每个阶段一个文档。

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

from pymongo import ReturnDocument

from bdm import db

STAGES = ('fetch', 'download', 'upload', 'match')

STAGE_LABELS = {
    'fetch': '获取动态',
    'download': '下载视频',
    'upload': '上传云盘',
    'match': '识别BGM',
}

WORKER_HEARTBEAT_KEY = 'worker_heartbeat'


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


def _update(name, fields):
    db.task_state().update_one({'name': name}, {'$set': {**fields, 'updated_at': _now()}}, upsert=True)


def ensure_all():
    for name in STAGES:
        db.task_state().update_one({'name': name}, {'$setOnInsert': _defaults(name)}, upsert=True)


def get(name):
    doc = db.task_state().find_one({'name': name}, {'_id': 0}) or {}
    return {**_defaults(name), **doc}


def all_states():
    docs = {d['name']: d for d in db.task_state().find({'name': {'$in': list(STAGES)}}, {'_id': 0})}
    return [{**_defaults(n), **docs.get(n, {})} for n in STAGES]


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
    names = []
    for doc in db.task_state().find({'run_requested': True}, {'name': 1}):
        res = db.task_state().update_one({'name': doc['name'], 'run_requested': True},
                                         {'$set': {'run_requested': False}})
        if res.modified_count:
            names.append(doc['name'])
    return names


def mark_started(name):
    _update(name, {'running': True, 'last_started_at': _now(), 'last_summary': None, 'error_in_run': False})


def mark_finished(name, status, fallback_error=None):
    now = _now()
    _update(name, {'running': False, 'last_finished_at': now, 'last_status': status})
    if fallback_error:
        # 子进程本轮已上报更具体的错误时不覆盖
        db.task_state().update_one(
            {'name': name, 'error_in_run': {'$ne': True}},
            {'$set': {'last_error': fallback_error, 'last_error_item': None, 'last_error_at': now}},
        )


def reset_running():
    db.task_state().update_many({'running': True}, {'$set': {'running': False}})


def report_summary(name, summary):
    _update(name, {'last_summary': summary})


def report_error(name, error, item=None):
    _update(name, {
        'last_error': str(error)[:1000], 'last_error_item': item, 'last_error_at': _now(), 'error_in_run': True,
    })


def record_item_failure(name):
    doc = db.task_state().find_one_and_update(
        {'name': name}, {'$inc': {'consecutive_failures': 1}}, upsert=True, return_document=ReturnDocument.AFTER,
    )
    return doc['consecutive_failures']


def reset_item_failures(name):
    _update(name, {'consecutive_failures': 0})


def heartbeat():
    db.set_setting(WORKER_HEARTBEAT_KEY, _now())


def last_heartbeat():
    return db.get_setting(WORKER_HEARTBEAT_KEY)
