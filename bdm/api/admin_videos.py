import logging

from flask import Blueprint, request
from flask_jwt_extended import verify_jwt_in_request

from bdm import cloud, db, media, videos
from bdm.api.common import (SONG_MATCHES, ApiError, body, int_arg, is_song_id, ok, page_args, paginate,
                            search_ups, vids_from)
from bdm.status import DStatus, ShazamStatus, UStatus

logger = logging.getLogger(__name__)

bp = Blueprint('admin_videos', __name__, url_prefix='/api/admin/videos')

FILTERS = {
    'all': None,
    'pending': f'dstatus IN ({DStatus.PENDING}, {DStatus.DOWNLOADING})',
    'local': f'dstatus = {DStatus.LOCAL}',
    'archived': f'dstatus = {DStatus.CLOUD}',
    'download_failed': 'dstatus < 0',
    'upload_failed': f'dstatus = {DStatus.LOCAL} AND fid IS NULL AND cloud_retry > 0',
    'selected': f'ustatus > {UStatus.DEFAULT}',
    'low_res': f'(low_res = 1 OR dstatus = {DStatus.LOW_RES})',
}


@bp.before_request
def require_admin():
    verify_jwt_in_request()


def _in_vids(vids):
    return f'vid IN ({db.marks(vids)})'


def _find(vids):
    return db.find_videos(_in_vids(vids), vids)


@bp.get('')
def list_videos():
    status = request.args.get('filter') or 'all'
    if status not in FILTERS:
        raise ApiError(f'filter 可选值：{", ".join(FILTERS)}')
    page, size = page_args(50, 200)

    clauses = [FILTERS[status]] if FILTERS[status] else []
    params = []
    uid = int_arg('uid')
    if uid:
        clauses.append('uid = ?')
        params.append(uid)
    keyword = (request.args.get('keyword') or '').strip()
    if keyword:
        clauses.append(f'(vid = ? OR {SONG_MATCHES} OR icontains(title, ?) OR icontains(etitle, ?) '
                       f'OR icontains(uname, ?))')
        params.extend([keyword] * 5)

    data = paginate(' AND '.join(clauses) or '1', params, page, size)
    if keyword:
        data['ups'] = search_ups(keyword)
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
    if db.get_video(vid):
        raise ApiError('稿件已存在', 409)
    try:
        doc = videos.from_import(source, pure_vid, p)
    except Exception as err:
        raise ApiError(f'解析稿件失败：{err}', 502)
    if not db.insert_video(doc):
        raise ApiError('稿件已存在', 409)
    return ok({'vid': vid}, '导入成功')


@bp.post('/select')
def select():
    data = body()
    vids = vids_from(data)
    selected = data.get('selected', True) is not False
    ustatus = UStatus.SELECTED if selected else UStatus.DEFAULT
    modified = db.update_videos(_in_vids(vids), vids, set={'ustatus': ustatus})
    return ok({'modified': modified}, '已精选' if selected else '已取消精选')


@bp.post('/retry-download')
def retry_download():
    """重新下载。已有的本地和云盘文件先保留，新版本下载成功后才会替换。"""
    vids = vids_from(body())
    queued = db.update_videos(
        f'{_in_vids(vids)} AND dstatus != {DStatus.DOWNLOADING}', vids,
        set={'dstatus': DStatus.PENDING, 'dl_retry': 0, 'dl_requested': True}, unset=['dl_error'],
    )
    return ok({'queued': queued}, f'已重新加入下载队列 {queued} 个')


@bp.post('/retry-upload')
def retry_upload():
    vids = vids_from(body())
    modified = db.update_videos(
        f'{_in_vids(vids)} AND dstatus = {DStatus.LOCAL} AND fid IS NULL', vids,
        set={'cloud_retry': 0}, unset=['cloud_error'],
    )
    return ok({'modified': modified}, f'已重新加入上传队列 {modified} 个')


@bp.post('/reset-bgm')
def reset_bgm():
    vids = vids_from(body())
    modified = db.update_videos(f'{_in_vids(vids)} AND dstatus = {DStatus.LOCAL}', vids,
                                set={'shazam_id': ShazamStatus.PENDING})
    return ok({'modified': modified}, f'已重置 {modified} 个（仅对本地文件仍在的稿件生效）')


def _delete(items):
    for item in items:
        cloud.delete_video_files(item)
        media.remove_local_files(item)
        db.delete_video(item['vid'])
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
    where, params = f'ustatus = {UStatus.DEFAULT} AND pdate BETWEEN ? AND ?', [start, end]
    if data.get('uid'):
        where += ' AND uid = ?'
        params.append(int(data['uid']))
    count = _delete(db.find_videos(where, params))
    return ok({'deleted': count}, f'共删除 {count} 个稿件')


@bp.put('/<vid>/owner')
def set_owner(vid):
    data = body()
    try:
        uid = int(data['uid'])
    except (KeyError, TypeError, ValueError):
        raise ApiError('uid 必须是整数')
    uname = str(data.get('uname') or '').strip()
    if not db.update_videos('vid = ?', (vid,), set={'uid': uid, 'uname': uname}, only_changed=False):
        raise ApiError('稿件不存在', 404)
    return ok(None, '已修改 UP 主')


@bp.put('/<vid>/bgm-title')
def set_bgm_title(vid):
    title = str(body().get('title') or '').strip()
    item = db.get_video(vid)
    if not item:
        raise ApiError('稿件不存在', 404)
    if is_song_id(item.get('shazam_id')):
        db.execute('INSERT INTO songs (id, title) VALUES (?, ?) ON CONFLICT (id) DO UPDATE SET title = excluded.title',
                   (item['shazam_id'], title))
        return ok({'scope': 'song'}, '已修改曲目标题（影响所有使用该曲目的稿件）')
    db.update_videos('vid = ?', (vid,), set={'etitle': title})
    return ok({'scope': 'video'}, '已修改稿件的 BGM 标题')
