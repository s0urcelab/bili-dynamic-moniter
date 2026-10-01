"""
把本地（LOCAL）且尚未上传的稿件传到天翼云盘。

单个稿件失败会累加 cloud_retry，达到上限后不再自动重试；
连续 UPLOAD_PAUSE_THRESHOLD 个稿件失败（通常是登录失效或云盘异常）时自动暂停本阶段。
"""
import logging
from datetime import datetime, timezone

from bdm import cloud, config, db, media, videos
from bdm.status import DStatus
from bdm.tasks import state

logger = logging.getLogger(__name__)

STAGE = 'upload'


def candidates(limit):
    q = {
        'dstatus': DStatus.LOCAL,
        'fid': {'$in': [None, '']},
        'cloud_retry': {'$not': {'$gte': config.MAX_UPLOAD_RETRY}},
    }
    return list(db.videos().find(q, {'_id': 0}).sort('pdate', -1).limit(limit))


def upload_one(item):
    """返回 False 表示本地文件缺失、已退回下载阶段。"""
    vid = item['vid']
    files = media.video_files(item)
    if not files:
        logger.warning('本地文件不存在，退回下载阶段：%s', vid)
        db.videos().update_one({'vid': vid}, {'$set': {
            'dstatus': DStatus.FILE_MISSING, 'dl_error': '上传时找不到本地文件',
        }})
        return False

    if item.get('stale_fid') or item.get('stale_cover_fid'):
        # 新版本已在本地，先删除云盘上被替换的旧版本，避免同名冲突
        cloud.delete_files(vid, item.get('stale_fid'), item.get('stale_cover_fid'))
        db.videos().update_one({'vid': vid}, {'$unset': {'stale_fid': '', 'stale_cover_fid': ''}})

    logger.info('开始上传：%s %s', item['title'], vid)
    fields = {'fid': cloud.upload(files[0], vid), 'uploaded_at': datetime.now(timezone.utc)}

    covers = media.cover_files(item)
    if covers:
        try:
            fields['cover_fid'] = cloud.upload(covers[0], vid)
        except Exception as err:
            logger.warning('封面上传失败 %s：%s', vid, err)

    db.videos().update_one({'vid': vid}, {'$set': fields, '$unset': {'cloud_error': ''}})
    logger.info('上传成功：%s %s', item['title'], vid)
    videos.finalize(vid)
    return True


def run():
    items = candidates(config.UPLOAD_BATCH)
    if not items:
        return '没有待上传的稿件'

    ok = failed = 0
    for item in items:
        if not state.is_enabled(STAGE):
            logger.info('上传已被关闭，停止本轮')
            break
        try:
            if upload_one(item):
                ok += 1
            state.reset_item_failures(STAGE)
        except Exception as err:
            failed += 1
            cloud.reset()
            message = f'{type(err).__name__}: {err}'
            logger.exception('上传失败：%s', item['vid'])
            db.videos().update_one({'vid': item['vid']}, {
                '$set': {'cloud_error': message[:500]},
                '$inc': {'cloud_retry': 1},
            })
            state.report_error(STAGE, message, f'[{item["vid"]}] {item["title"]}')

            streak = state.record_item_failure(STAGE)
            if streak >= config.UPLOAD_PAUSE_THRESHOLD:
                state.pause(STAGE, f'连续 {streak} 个稿件上传失败，已自动暂停。最近错误：{message}')
                logger.error('上传连续失败 %d 次，已自动暂停', streak)
                break
    return f'上传成功 {ok} 个，失败 {failed} 个'
