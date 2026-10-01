from flask import Blueprint, request

from bdm import db
from bdm.api.auth import is_admin
from bdm.api.common import (PUBLISHED, SONG_MATCHES, ApiError, attach, int_arg, ok, page_args, paginate,
                            play_url, search_ups, ups_by_uid)

bp = Blueprint('public', __name__, url_prefix='/api')


@bp.get('/videos')
def list_videos():
    page, size = page_args(15, 50)
    where, params = PUBLISHED, ()
    uid = int_arg('uid')
    if uid:
        where, params = f'{PUBLISHED} AND uid = ?', (uid,)
    return ok(paginate(where, params, page, size))


@bp.get('/videos/<vid>')
def video_detail(vid):
    item = db.find_video('vid = ?' if is_admin() else f'{PUBLISHED} AND vid = ?', (vid,))
    if not item:
        raise ApiError('稿件不存在', 404)

    url, error = play_url(item)
    related = db.find_videos(f'{PUBLISHED} AND uid = ? AND vid != ?', (item['uid'], vid), limit=6)
    return ok({
        'video': attach([item])[0],
        'play_url': url,
        'play_error': error,
        'related': attach(related),
    })


@bp.get('/search')
def search():
    keyword = (request.args.get('keyword') or '').strip()
    if not keyword:
        raise ApiError('缺少关键词 keyword')
    videos = db.find_videos(
        f'{PUBLISHED} AND ({SONG_MATCHES} OR icontains(title, ?) OR icontains(etitle, ?))',
        (keyword,) * 3, limit=50,
    )
    return ok({'ups': search_ups(keyword), 'videos': attach(videos)})


UP_SORTS = {
    'recent': 'latest_at DESC, uid',
    'count': 'video_count DESC, uid',
}

# 按 uid 汇总已发布稿件。uname/avatar 取 pdate 最大的那条（SQLite 对 MAX() 旁的裸列保证这一点），
# 作为关注列表里没有时的回退
_UP_STATS = f"""
    SELECT uid, COUNT(*) AS video_count, MAX(pdate) AS latest_at, uname, avatar
    FROM videos WHERE {PUBLISHED} {{extra}} GROUP BY uid
"""


def _up_item(uid, stats, up):
    stats = stats or {}
    up = up or {}
    return {
        'uid': uid,
        'uname': up.get('uname') or stats.get('uname'),
        'avatar': up.get('avatar') or stats.get('avatar'),
        'sign': up.get('sign', ''),
        'video_count': stats.get('video_count', 0),
        'latest_at': stats.get('latest_at'),
    }


@bp.get('/ups')
def list_ups():
    page, size = page_args(20, 100)
    sort = request.args.get('sort') or 'recent'
    if sort not in UP_SORTS:
        raise ApiError('参数 sort 只能是 recent 或 count')
    total = db.scalar(f'SELECT COUNT(DISTINCT uid) FROM videos WHERE {PUBLISHED}')
    rows = db.query(f'{_UP_STATS.format(extra="")} ORDER BY {UP_SORTS[sort]} LIMIT ? OFFSET ?',
                    (size, (page - 1) * size))
    ups = ups_by_uid(r['uid'] for r in rows)
    items = [_up_item(r['uid'], r, ups.get(r['uid'])) for r in rows]
    return ok({'items': items, 'total': total, 'page': page, 'size': size})


@bp.get('/ups/<int:uid>')
def up_info(uid):
    stats = db.query_one(_UP_STATS.format(extra='AND uid = ?'), (uid,))
    up = db.query_one('SELECT * FROM ups WHERE uid = ?', (uid,))
    if not up and not stats:
        # 不在关注列表、也没有已发布稿件时，用任意一条稿件记录兜底（前台只认已发布的）
        if not is_admin():
            raise ApiError('UP 主不存在', 404)
        up = db.query_one('SELECT uname, avatar FROM videos WHERE uid = ? ORDER BY pdate DESC LIMIT 1', (uid,))
        if not up:
            raise ApiError('UP 主不存在', 404)
    return ok(_up_item(uid, stats, up))
