import logging
from datetime import date, datetime

from flask import jsonify, request
from flask.json.provider import DefaultJSONProvider

from bdm import cloud, db, media
from bdm.status import DSTATUS_LABELS, ShazamStatus, UStatus

logger = logging.getLogger(__name__)

MAX_BATCH = 500

# 前台可见：精选且本地/云盘
PUBLISHED = db.PUBLISHED

# BGM 曲目标题包含关键词，参数为关键词
SONG_MATCHES = 'song_id IN (SELECT id FROM songs WHERE icontains(title, ?))'


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


class JSONProvider(DefaultJSONProvider):
    ensure_ascii = False
    sort_keys = False

    @staticmethod
    def default(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return DefaultJSONProvider.default(o)


def ok(data=None, message='ok'):
    return jsonify({'code': 0, 'message': message, 'data': data})


def fail(message, status):
    return jsonify({'code': status, 'message': message, 'data': None}), status


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError('请求体必须是 JSON 对象')
    return data


def vids_from(data):
    vids = data.get('vids')
    if not isinstance(vids, list) or not vids or not all(isinstance(v, str) and v for v in vids):
        raise ApiError('vids 必须是非空的字符串数组')
    if len(vids) > MAX_BATCH:
        raise ApiError(f'单次最多处理 {MAX_BATCH} 个稿件')
    return list(dict.fromkeys(vids))


def int_arg(name, default=None, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw in (None, ''):
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ApiError(f'参数 {name} 必须是整数')
    if minimum is not None:
        value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    return value


def is_song_id(shazam_id):
    return shazam_id not in (ShazamStatus.PENDING, ShazamStatus.NO_MATCH, ShazamStatus.NO_FILE,
                             ShazamStatus.ERROR, None)


def ups_by_uid(uids):
    uids = list(uids)
    if not uids:
        return {}
    return {u['uid']: u for u in db.query(f'SELECT * FROM ups WHERE uid IN ({db.marks(uids)})', uids)}


def search_ups(keyword, limit=20):
    return db.query('SELECT * FROM ups WHERE icontains(uname, ?) LIMIT ?', (keyword, limit))


def attach(items):
    """批量补充 BGM 标题与 UP 主信息。"""
    items = list(items)
    song_ids = list({i['shazam_id'] for i in items if is_song_id(i.get('shazam_id'))})
    songs = {s['id']: s['title'] for s in db.query(
        f'SELECT id, title FROM songs WHERE id IN ({db.marks(song_ids)})', song_ids)} if song_ids else {}
    ups = ups_by_uid({i['uid'] for i in items if i.get('uid') is not None})

    result = []
    for item in items:
        up = ups.get(item.get('uid'))
        item['bgm_title'] = songs.get(item.get('shazam_id')) or item.get('etitle')
        item['up'] = {
            'uid': item.get('uid'),
            'uname': up['uname'] if up else item.get('uname'),
            'avatar': up['avatar'] if up else item.get('avatar'),
            'sign': up.get('sign', '') if up else '',
        }
        item['selected'] = item.get('ustatus', 0) > UStatus.DEFAULT
        item['dstatus_label'] = DSTATUS_LABELS.get(item.get('dstatus'), '未知')
        result.append(item)
    return result


def paginate(where, params, page, size):
    """按发布时间倒序分页。"""
    total = db.count_videos(where, params)
    items = db.find_videos(where, params, limit=size, offset=(page - 1) * size)
    return {'items': attach(items), 'total': total, 'page': page, 'size': size}


def page_args(default_size, max_size):
    return int_arg('page', 1, minimum=1), int_arg('size', default_size, minimum=1, maximum=max_size)


def play_url(item):
    """返回 (播放地址, 错误信息)。优先云盘，其次本地文件。"""
    if item.get('fid'):
        try:
            return cloud.play_url(item['fid']), None
        except Exception as err:
            logger.warning('获取云盘播放地址失败 %s：%s', item['vid'], err)
            cloud.reset()
            return None, '获取云盘播放地址失败'
    files = media.video_files(item)
    if files:
        url = media.local_url(files[0])
        return url, None if url else '未配置 LOCAL_FILE_URL_PREFIX'
    return None, '文件不存在'
