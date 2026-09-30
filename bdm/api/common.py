import logging
import re
from datetime import date, datetime

from bson import ObjectId
from flask import jsonify, request
from flask.json.provider import DefaultJSONProvider

from bdm import cloud, db, media
from bdm.status import DSTATUS_LABELS, DStatus, ShazamStatus, UStatus

logger = logging.getLogger(__name__)

MAX_BATCH = 500

# 前台可见：精选且已下载
PUBLISHED = {'ustatus': {'$gt': UStatus.DEFAULT}, 'dstatus': {'$gte': DStatus.LOCAL}}


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
        if isinstance(o, ObjectId):
            return str(o)
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


def keyword_regex(keyword):
    return {'$regex': re.escape(keyword), '$options': 'i'}


def is_song_id(shazam_id):
    return shazam_id not in (ShazamStatus.PENDING, ShazamStatus.NO_MATCH, ShazamStatus.NO_FILE,
                             ShazamStatus.ERROR, None)


def song_ids_matching(regex):
    return [s['id'] for s in db.songs().find({'title': regex}, {'id': 1})]


def attach(items):
    """批量补充 BGM 标题与 UP 主信息。"""
    items = list(items)
    song_ids = list({i['shazam_id'] for i in items if is_song_id(i.get('shazam_id'))})
    uids = list({i['uid'] for i in items if i.get('uid') is not None})
    songs = {s['id']: s['title'] for s in db.songs().find({'id': {'$in': song_ids}})} if song_ids else {}
    ups = {u['uid']: u for u in db.ups().find({'uid': {'$in': uids}}, {'_id': 0})} if uids else {}

    result = []
    for item in items:
        item = {k: v for k, v in item.items() if k != '_id'}
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


def paginate(query, page, size, sort=('pdate', -1)):
    total = db.videos().count_documents(query)
    cursor = db.videos().find(query, {'_id': 0}).sort(*sort).skip((page - 1) * size).limit(size)
    return {'items': attach(cursor), 'total': total, 'page': page, 'size': size}


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
