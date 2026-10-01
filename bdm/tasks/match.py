"""用 Shazam 识别本地稿件的 BGM。"""
import asyncio
import logging

from shazamio import Serialize, Shazam

from bdm import config, db, media, videos
from bdm.status import DStatus, ShazamStatus
from bdm.tasks import state

logger = logging.getLogger(__name__)

STAGE = 'match'


def candidates(limit):
    return db.find_videos(f'bgm_status = {ShazamStatus.PENDING} AND dstatus = {DStatus.LOCAL}', limit=limit)


async def recognize(shazam, path):
    """返回 (shazam_id, 曲名)；没有匹配时返回 (NO_MATCH, None)。"""
    raw = await shazam.recognize_song(path)
    result = Serialize.full_track(raw)
    if not result.matches:
        return ShazamStatus.NO_MATCH, None
    return result.matches[0].id, result.track.title


async def match_all(items):
    shazam = Shazam()
    counts = {'matched': 0, 'no_match': 0, 'failed': 0}
    for item in items:
        if not state.is_enabled(STAGE):
            logger.info('BGM 识别已被关闭，停止本轮')
            break
        vid = item['vid']
        files = media.video_files(item)
        if not files:
            shazam_id, title = ShazamStatus.NO_FILE, None
            logger.error('BGM 识别失败，本地文件不存在：%s', vid)
        else:
            try:
                shazam_id, title = await recognize(shazam, files[0])
            except Exception as err:
                shazam_id, title = ShazamStatus.ERROR, None
                logger.exception('Shazam 识别异常：%s', vid)
                state.report_error(STAGE, f'{type(err).__name__}: {err}', f'[{vid}] {item["title"]}')

        if shazam_id not in (ShazamStatus.NO_MATCH, ShazamStatus.NO_FILE, ShazamStatus.ERROR):
            # 稿件通过外键引用曲目，曲目要先写入；已存在的曲目保留后台手动修改过的标题
            db.execute('INSERT INTO songs (id, title) VALUES (?, ?) ON CONFLICT (id) DO NOTHING',
                       (str(shazam_id), title or ''))
        db.update_videos('vid = ?', (vid,), set={'shazam_id': shazam_id})
        if title:
            counts['matched'] += 1
        elif shazam_id == ShazamStatus.NO_MATCH:
            counts['no_match'] += 1
        else:
            counts['failed'] += 1
        videos.finalize(vid)
    return counts


def run():
    items = candidates(config.MATCH_BATCH)
    if not items:
        return '没有待识别的稿件'
    counts = asyncio.run(match_all(items))
    return f'识别成功 {counts["matched"]} 个，无匹配 {counts["no_match"]} 个，失败 {counts["failed"]} 个'
