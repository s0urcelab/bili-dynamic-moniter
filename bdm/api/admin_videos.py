import logging

from flask import Blueprint, request
from flask_jwt_extended import verify_jwt_in_request
from pymongo.errors import DuplicateKeyError

from bdm import cloud, db, media, videos
from bdm.api.common import (ApiError, body, int_arg, is_song_id, keyword_regex, ok, page_args, paginate,
                            song_ids_matching, vids_from)
from bdm.status import DStatus, ShazamStatus, UStatus

logger = logging.getLogger(__name__)

bp = Blueprint('admin_videos', __name__, url_prefix='/api/admin/videos')

FILTERS = {
    'all': {},
    'pending': {'dstatus': {'$in': [DStatus.PENDING, DStatus.DOWNLOADING]}},
    'local': {'dstatus': DStatus.LOCAL},
    'archived': {'dstatus': DStatus.CLOUD},
    'download_failed': {'dstatus': {'$lt': 0}},
    'upload_failed': {'dstatus': DStatus.LOCAL, 'fid': {'$in': [None, '']}, 'cloud_retry': {'$gt': 0}},
    'selected': {'ustatus': {'$gt': UStatus.DEFAULT}},
    'low_res': {'$or': [{'low_res': True}, {'dstatus': DStatus.LOW_RES}]},
}


@bp.before_request
def require_admin():
    verify_jwt_in_request()


def _find(vids):
    return list(db.videos().find({'vid': {'$in': vids}}, {'_id': 0}))


@bp.get('')
def list_videos():
    status = request.args.get('filter') or 'all'
    if status not in FILTERS:
        raise ApiError(f'filter 可选值：{", ".join(FILTERS)}')
    page, size = page_args(50, 200)

    clauses = [FILTERS[status]]
    uid = int_arg('uid')
    if uid:
        clauses.append({'uid': uid})
    keyword = (request.args.get('keyword') or '').strip()
    if keyword:
        regex = keyword_regex(keyword)
        clauses.append({'$or': [
            {'vid': keyword},
            {'shazam_id': {'$in': song_ids_matching(regex)}},
            {'title': regex},
            {'etitle': regex},
            {'uname': regex},
        ]})

    data = paginate({'$and': clauses}, page, size)
    if keyword:
        data['ups'] = list(db.ups().find({'uname': keyword_regex(keyword)}, {'_id': 0}).limit(20))
    return ok(data)


@bp.post('/import')
def import_video():
    data = body()
    source = data.get('source')
    pure_vid = str(data.get('vid') or '').strip()
    try:
        p = int(data.get('p') or 1)
    except (TypeError, ValueError):
        raise ApiError('p 必须是整数')
    if source not in ('bilibili', 'acfun') or not pure_vid or p < 1:
        raise ApiError('需要 source(bilibili|acfun)、vid，以及可选的 p（从 1 开始）')

    vid = videos.import_vid(pure_vid, p)
    if db.videos().count_documents({'vid': vid}, limit=1):
        raise ApiError('稿件已存在', 409)
    try:
        doc = videos.from_import(source, pure_vid, p)
    except Exception as err:
        raise ApiError(f'解析稿件失败：{err}', 502)
    try:
        db.videos().insert_one(doc)
    except DuplicateKeyError:
        raise ApiError('稿件已存在', 409)
    return ok({'vid': vid}, '导入成功')


@bp.post('/select')
def select():
    data = body()
    vids = vids_from(data)
    selected = data.get('selected', True) is not False
    ustatus = UStatus.SELECTED if selected else UStatus.DEFAULT
    res = db.videos().update_many({'vid': {'$in': vids}}, {'$set': {'ustatus': ustatus}})
    return ok({'modified': res.modified_count}, '已精选' if selected else '已取消精选')


@bp.post('/retry-download')
def retry_download():
    """重新下载。已有的本地和云盘文件先保留，新版本下载成功后才会替换。"""
    vids = vids_from(body())
    res = db.videos().update_many(
        {'vid': {'$in': vids}, 'dstatus': {'$ne': DStatus.DOWNLOADING}},
        {'$set': {'dstatus': DStatus.PENDING, 'dl_retry': 0, 'dl_requested': True}, '$unset': {'dl_error': ''}},
    )
    return ok({'queued': res.modified_count}, f'已重新加入下载队列 {res.modified_count} 个')


@bp.post('/retry-upload')
def retry_upload():
    vids = vids_from(body())
    res = db.videos().update_many(
        {'vid': {'$in': vids}, 'dstatus': DStatus.LOCAL, 'fid': {'$in': [None, '']}},
        {'$set': {'cloud_retry': 0}, '$unset': {'cloud_error': ''}},
    )
    return ok({'modified': res.modified_count}, f'已重新加入上传队列 {res.modified_count} 个')


@bp.post('/reset-bgm')
def reset_bgm():
    vids = vids_from(body())
    res = db.videos().update_many(
        {'vid': {'$in': vids}, 'dstatus': DStatus.LOCAL},
        {'$set': {'shazam_id': ShazamStatus.PENDING}},
    )
    return ok({'modified': res.modified_count}, f'已重置 {res.modified_count} 个（仅对本地文件仍在的稿件生效）')


def _delete(items):
    for item in items:
        cloud.delete_video_files(item)
        media.remove_local_files(item)
        db.videos().delete_one({'vid': item['vid']})
    return len(items)


@bp.post('/delete')
def delete():
    count = _delete(_find(vids_from(body())))
    return ok({'deleted': count}, f'已删除 {count} 个稿件')


@bp.post('/delete-range')
def delete_range():
    """删除发布时间在 [start, end] 内、未精选的稿件及其文件。"""
    data = body()
    try:
        start, end = int(data['start']), int(data['end'])
    except (KeyError, TypeError, ValueError):
        raise ApiError('start、end 必须是秒级时间戳')
    if start > end:
        raise ApiError('start 不能大于 end')
    query = {'ustatus': UStatus.DEFAULT, 'pdate': {'$gte': start, '$lte': end}}
    if data.get('uid'):
        query['uid'] = int(data['uid'])
    count = _delete(list(db.videos().find(query, {'_id': 0})))
    return ok({'deleted': count}, f'共删除 {count} 个稿件')


@bp.put('/<vid>/owner')
def set_owner(vid):
    data = body()
    try:
        uid = int(data['uid'])
    except (KeyError, TypeError, ValueError):
        raise ApiError('uid 必须是整数')
    uname = str(data.get('uname') or '').strip()
    res = db.videos().update_one({'vid': vid}, {'$set': {'uid': uid, 'uname': uname}})
    if not res.matched_count:
        raise ApiError('稿件不存在', 404)
    return ok(None, '已修改 UP 主')


@bp.put('/<vid>/bgm-title')
def set_bgm_title(vid):
    title = str(body().get('title') or '').strip()
    item = db.videos().find_one({'vid': vid}, {'shazam_id': 1})
    if not item:
        raise ApiError('稿件不存在', 404)
    if is_song_id(item.get('shazam_id')):
        db.songs().update_one({'id': item['shazam_id']}, {'$set': {'title': title}}, upsert=True)
        return ok({'scope': 'song'}, '已修改曲目标题（影响所有使用该曲目的稿件）')
    db.videos().update_one({'vid': vid}, {'$set': {'etitle': title}})
    return ok({'scope': 'video'}, '已修改稿件的 BGM 标题')
