from flask import Blueprint, request

from bdm import db
from bdm.api.auth import is_admin
from bdm.api.common import (PUBLISHED, ApiError, attach, int_arg, keyword_regex, ok, page_args,
                            paginate, play_url, song_ids_matching)

bp = Blueprint('public', __name__, url_prefix='/api')


@bp.get('/videos')
def list_videos():
    page, size = page_args(15, 50)
    query = dict(PUBLISHED)
    uid = int_arg('uid')
    if uid:
        query['uid'] = uid
    return ok(paginate(query, page, size))


@bp.get('/videos/<vid>')
def video_detail(vid):
    query = {'vid': vid} if is_admin() else {**PUBLISHED, 'vid': vid}
    item = db.videos().find_one(query, {'_id': 0})
    if not item:
        raise ApiError('稿件不存在', 404)

    url, error = play_url(item)
    related = db.videos().find(
        {**PUBLISHED, 'uid': item['uid'], 'vid': {'$ne': vid}}, {'_id': 0},
    ).sort('pdate', -1).limit(6)
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
    regex = keyword_regex(keyword)
    ups = list(db.ups().find({'uname': regex}, {'_id': 0}).limit(20))
    query = {**PUBLISHED, '$or': [
        {'shazam_id': {'$in': song_ids_matching(regex)}},
        {'title': regex},
        {'etitle': regex},
    ]}
    videos = db.videos().find(query, {'_id': 0}).sort('pdate', -1).limit(50)
    return ok({'ups': ups, 'videos': attach(videos)})


UP_SORTS = {
    'recent': {'latest_at': -1, '_id': 1},
    'count': {'video_count': -1, '_id': 1},
}

# 按 uid 汇总已发布稿件，uname/avatar 取最新一个稿件上的，作为关注列表里没有时的回退
_UP_STATS = [
    {'$match': PUBLISHED},
    {'$sort': {'pdate': -1}},
    {'$group': {
        '_id': '$uid',
        'video_count': {'$sum': 1},
        'latest_at': {'$first': '$pdate'},
        'uname': {'$first': '$uname'},
        'avatar': {'$first': '$avatar'},
    }},
]


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
    result = next(db.videos().aggregate([
        *_UP_STATS,
        {'$match': {'_id': {'$ne': None}}},
        {'$facet': {
            'total': [{'$count': 'n'}],
            'items': [{'$sort': UP_SORTS[sort]}, {'$skip': (page - 1) * size}, {'$limit': size}],
        }},
    ]), {})
    rows = result.get('items', [])
    total = result['total'][0]['n'] if result.get('total') else 0
    uids = [r['_id'] for r in rows]
    ups = {u['uid']: u for u in db.ups().find({'uid': {'$in': uids}}, {'_id': 0})} if uids else {}
    items = [_up_item(r['_id'], r, ups.get(r['_id'])) for r in rows]
    return ok({'items': items, 'total': total, 'page': page, 'size': size})


@bp.get('/ups/<int:uid>')
def up_info(uid):
    stats = next(db.videos().aggregate([{'$match': {'uid': uid}}, *_UP_STATS]), None)
    up = db.ups().find_one({'uid': uid}, {'_id': 0})
    if not up and not stats:
        # 不在关注列表、也没有已发布稿件时，用任意一条稿件记录兜底（前台只认已发布的）
        if not is_admin():
            raise ApiError('UP 主不存在', 404)
        video = db.videos().find_one({'uid': uid}, {'uname': 1, 'avatar': 1}, sort=[('pdate', -1)])
        if not video:
            raise ApiError('UP 主不存在', 404)
        up = video
    return ok(_up_item(uid, stats, up))
