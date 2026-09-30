"""获取关注分组内 UP 主在截止时间（check_point）之后发布的视频动态。"""
import logging
import time

from pymongo import UpdateOne
from pymongo.errors import BulkWriteError

from bdm import config, cookies, db, videos
from bdm.bilibili import SPECIAL_FOLLOW_TAG_ID, BiliAuthError, BiliClient, format_ts, parse_feed_item

logger = logging.getLogger(__name__)


def refresh_follow(bili):
    try:
        members = bili.tag_members(config.BILI_FOLLOW_TAG_ID)
    except BiliAuthError:
        raise
    except Exception as err:
        cached = db.get_setting('follow_list')
        if cached is None:
            raise
        logger.warning('获取关注分组失败，沿用上次的关注列表：%s', err)
        follow = cached
    else:
        follow = [m['mid'] for m in members]
        db.set_setting('follow_list', follow)
        if members:
            db.ups().bulk_write([
                UpdateOne({'uid': m['mid']}, {'$set': {
                    'uname': m['uname'], 'avatar': m['face'], 'sign': m.get('sign', ''),
                }}, upsert=True)
                for m in members
            ], ordered=False)

    try:
        special = [m['mid'] for m in bili.tag_members(SPECIAL_FOLLOW_TAG_ID)]
        db.set_setting('special_follow_list', special)
    except BiliAuthError:
        raise
    except Exception as err:
        logger.warning('获取特别关注失败，沿用上次的列表：%s', err)
        special = db.get_setting('special_follow_list', [])

    logger.info('关注分组共 %d 位 UP 主，特别关注 %d 位', len(follow), len(special))
    return set(follow), set(special)


def collect_feed(bili, checkpoint):
    """按时间倒序翻页，直到遇到截止时间之前的动态。返回 (动态列表, 是否已到达截止时间)。"""
    items = []
    offset = ''
    for page in range(1, config.MAX_DYNAMIC_FETCH_PAGE + 1):
        raw_items, offset, has_more = bili.feed_page(page, offset)
        for raw in raw_items:
            item = parse_feed_item(raw)
            if item is None:
                continue
            if item['pdate'] <= checkpoint:
                return items, True
            items.append(item)
        if not has_more:
            return items, True
    return items, False


def run():
    bili = BiliClient(cookies.subscribe_cookies())
    try:
        return _run(bili)
    except BiliAuthError:
        cookies.check('subscribe')
        raise


def _run(bili):
    follow, special = refresh_follow(bili)

    checkpoint = db.get_setting('check_point')
    if checkpoint is None:
        db.set_setting('check_point', int(time.time()))
        return '未设置动态截止时间，已初始化为当前时间'

    items, reached = collect_feed(bili, checkpoint)
    if not reached:
        logger.warning('已翻 %d 页仍未到达截止时间，更早的动态将被跳过', config.MAX_DYNAMIC_FETCH_PAGE)

    targets = [i for i in items if i['uid'] in follow]
    existing = {d['vid'] for d in db.videos().find({'vid': {'$in': [i['vid'] for i in targets]}}, {'vid': 1})}

    docs = []
    for item in targets:
        if item['vid'] in existing:
            continue
        try:
            meta = bili.video_meta(item['vid'])
        except Exception as err:
            logger.error('获取稿件详情失败 %s：%s', item['vid'], err)
            meta = None
        docs.append(videos.from_feed(item, meta, item['uid'] in special))

    inserted = 0
    if docs:
        try:
            inserted = len(db.videos().insert_many(docs, ordered=False).inserted_ids)
        except BulkWriteError as err:
            inserted = err.details.get('nInserted', 0)

    if items:
        new_checkpoint = max(i['pdate'] for i in items)
        db.set_setting('check_point', new_checkpoint)
        logger.info('动态截止时间更新为 %s', format_ts(new_checkpoint))

    return f'扫描 {len(items)} 条动态，新增 {inserted} 个稿件'
