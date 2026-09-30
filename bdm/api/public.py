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


@bp.get('/ups/<int:uid>')
def up_info(uid):
    up = db.ups().find_one({'uid': uid}, {'_id': 0})
    if not up:
        raise ApiError('UP 主不存在', 404)
    up['video_count'] = db.videos().count_documents({**PUBLISHED, 'uid': uid})
    return ok(up)
