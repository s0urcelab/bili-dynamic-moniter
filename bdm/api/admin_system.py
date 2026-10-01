import logging
import time
from datetime import datetime, timezone
from importlib import metadata

from flask import Blueprint
from flask_jwt_extended import verify_jwt_in_request

from bdm import cloud, config, cookies, db, media
from bdm.api.common import ApiError, body, ok
from bdm.bilibili import format_ts
from bdm.status import DSTATUS_LABELS, DStatus, ShazamStatus, UStatus
from bdm.tasks import state, upload

logger = logging.getLogger(__name__)

bp = Blueprint('admin_system', __name__, url_prefix='/api/admin')

WORKER_OFFLINE_AFTER = 60


@bp.before_request
def require_admin():
    verify_jwt_in_request()


def _stage(name):
    if name not in state.STAGES:
        raise ApiError(f'未知阶段：{name}', 404)
    return name


def _task_view(doc):
    schedule = config.SCHEDULE[doc['name']]
    return {
        **{k: v for k, v in doc.items() if k != 'updated_at'},
        'label': state.STAGE_LABELS[doc['name']],
        'interval_minutes': schedule['interval'],
        'timeout_minutes': schedule['timeout'],
    }


@bp.get('/tasks')
def list_tasks():
    heartbeat = state.last_heartbeat()
    online = bool(heartbeat) and (datetime.now(timezone.utc) - heartbeat).total_seconds() < WORKER_OFFLINE_AFTER
    return ok({
        'worker': {'online': online, 'heartbeat_at': heartbeat},
        'tasks': [_task_view(d) for d in state.all_states()],
    })


@bp.patch('/tasks/<name>')
def update_task(name):
    name = _stage(name)
    enabled = body().get('enabled')
    if not isinstance(enabled, bool):
        raise ApiError('enabled 必须是布尔值')
    state.set_enabled(name, enabled)
    return ok(_task_view(state.get(name)), f'{state.STAGE_LABELS[name]}已{"开启" if enabled else "关闭"}')


@bp.post('/tasks/<name>/run')
def run_task(name):
    name = _stage(name)
    if not state.is_enabled(name):
        raise ApiError(f'{state.STAGE_LABELS[name]}已关闭，请先开启', 409)
    state.request_run(name)
    return ok(None, '已请求立即执行，worker 将在 10 秒内开始')


def _cookie_kind(kind):
    if kind not in cookies.KINDS:
        raise ApiError(f'未知的 cookie 类型：{kind}，可选 {", ".join(cookies.KINDS)}', 404)
    return kind


def _resume_download_if_paused_by_cookie(login):
    task = state.get('download')
    if login.get('logged_in') and not task['enabled'] and \
            (task.get('paused_reason') or '').startswith(cookies.PAUSE_REASON_PREFIX):
        state.set_enabled('download', True)
        return True
    return False


@bp.get('/cookies')
def list_cookies():
    return ok({kind: cookies.describe(kind) for kind in cookies.KINDS})


@bp.put('/cookies/<kind>')
def save_cookie(kind):
    kind = _cookie_kind(kind)
    content = body().get('content')
    if not isinstance(content, str):
        raise ApiError('content 必须是字符串')
    try:
        cookies.save(kind, content)
    except cookies.CookieError as err:
        raise ApiError(str(err))
    login = cookies.check(kind)
    resumed = kind == 'download' and _resume_download_if_paused_by_cookie(login)

    if login['logged_in'] is False:
        message = f'已保存，但检测为未登录：{login.get("error") or "cookie 无效或已过期"}'
    elif login['logged_in'] is None:
        message = f'已保存，登录状态检测失败：{login.get("error")}'
    else:
        message = f'已保存，登录账号：{login.get("uname")}' + ('，下载已自动恢复' if resumed else '')
    return ok({**cookies.describe(kind), 'download_resumed': resumed}, message)


@bp.delete('/cookies/<kind>')
def clear_cookie(kind):
    kind = _cookie_kind(kind)
    cookies.clear(kind)
    return ok(cookies.describe(kind), '已清除后台配置，将回退使用环境变量')


@bp.post('/cookies/<kind>/check')
def check_cookie(kind):
    kind = _cookie_kind(kind)
    login = cookies.check(kind)
    resumed = kind == 'download' and _resume_download_if_paused_by_cookie(login)
    return ok({**cookies.describe(kind), 'download_resumed': resumed})


@bp.get('/checkpoint')
def get_checkpoint():
    ts = db.get_setting('check_point')
    return ok({'timestamp': ts, 'datetime': format_ts(ts) if ts else None})


@bp.put('/checkpoint')
def set_checkpoint():
    data = body()
    if 'timestamp' in data:
        try:
            ts = int(data['timestamp'])
        except (TypeError, ValueError):
            raise ApiError('timestamp 必须是秒级时间戳')
    else:
        try:
            dt = datetime.strptime(str(data.get('datetime')), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            raise ApiError('需要 timestamp，或格式为 YYYY-MM-DD HH:MM:SS 的 datetime')
        ts = int(dt.replace(tzinfo=config.TZ).timestamp())
    if ts > time.time():
        raise ApiError('截止时间不能晚于当前时间')
    db.set_setting('check_point', ts)
    return ok({'timestamp': ts, 'datetime': format_ts(ts)}, '动态截止时间已更新')


@bp.get('/storage')
def storage():
    local_bytes = media.dir_size()
    cloud_info = {'used_bytes': None, 'total_bytes': None, 'error': None}
    try:
        cloud_info['used_bytes'], cloud_info['total_bytes'] = cloud.disk_usage()
    except Exception as err:
        logger.warning('获取云盘容量失败：%s', err)
        cloud.reset()
        cloud_info['error'] = '获取云盘容量失败'
    return ok({'local_bytes': local_bytes, 'cloud': cloud_info})


def _package_version(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


@bp.get('/versions')
def versions():
    return ok({'yt_dlp': _package_version('yt-dlp'), 'shazamio': _package_version('shazamio')})


@bp.get('/stats')
def stats():
    by_status = {
        row['dstatus']: row['count']
        for row in db.query('SELECT dstatus, COUNT(*) AS count FROM videos GROUP BY dstatus ORDER BY dstatus')
    }
    return ok({
        'total': sum(by_status.values()),
        'by_dstatus': [
            {'dstatus': k, 'label': DSTATUS_LABELS.get(k, '未知'), 'count': v}
            for k, v in by_status.items()
        ],
        'selected': db.count_videos(f'ustatus > {UStatus.DEFAULT}'),
        'waiting_upload': db.count_videos(upload.QUEUE),
        'waiting_match': db.count_videos(f'dstatus = {DStatus.LOCAL} AND bgm_status = {ShazamStatus.PENDING}'),
    })
