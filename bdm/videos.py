import logging
import time

from bdm import acfun, bilibili, db, media
from bdm.status import DStatus, ShazamStatus, Source, UStatus

logger = logging.getLogger(__name__)


def _pipeline_defaults():
    return {
        'shazam_id': ShazamStatus.PENDING,
        'dstatus': DStatus.PENDING,
        'dl_retry': 0,
        'cloud_retry': 0,
        'up_retry': 0,
    }


def from_feed(feed_item, meta, selected):
    """动态流中的稿件。meta 为 None 表示详情获取失败。"""
    doc = {'source': Source.DYNAMIC, **feed_item, **_pipeline_defaults()}
    doc['ustatus'] = UStatus.SELECTED if selected else UStatus.DEFAULT
    if meta is None:
        doc['dstatus'] = DStatus.DETAIL_FAILED
    elif meta['is_paid']:
        doc['dstatus'] = DStatus.PAID
    else:
        doc.update({k: meta[k] for k in ('cid', 'duration', 'is_portrait', 'max_quality')})
    return doc


def from_import(source, pure_vid, p):
    """手动导入的稿件，默认直接精选。"""
    if source == 'bilibili':
        meta = bilibili.BiliClient().video_meta(pure_vid, p)
        src = Source.IMPORT_BILI
    elif source == 'acfun':
        meta = acfun.video_meta(pure_vid, p)
        src = Source.IMPORT_ACFUN
    else:
        raise ValueError(f'不支持的来源：{source}')

    pdate = int(time.time())
    duration = meta['duration']
    mm, ss = divmod(duration, 60)
    meta.pop('is_paid', None)
    return {
        **meta,
        **_pipeline_defaults(),
        'source': src,
        'vid': import_vid(pure_vid, p),
        'pure_vid': pure_vid,
        'p': p,
        'pdate': pdate,
        'pdstr': bilibili.format_ts(pdate),
        'duration_text': f'{mm:02d}:{ss:02d}',
        'ustatus': UStatus.SELECTED,
    }


def import_vid(pure_vid, p):
    return f'{pure_vid}[p{p}]' if p > 1 else pure_vid


def download_url(item):
    vid = item.get('pure_vid') or item['vid']
    p = item.get('p') or 1
    if item.get('source') == Source.IMPORT_ACFUN:
        return acfun.video_url(vid, p)
    return bilibili.video_url(vid, p)


def finalize(vid):
    """上传和 BGM 识别都完成后，清理本地文件并标记为已归档。"""
    item = db.videos().find_one({'vid': vid})
    if not item or item.get('dstatus') != DStatus.LOCAL:
        return
    if not item.get('fid') or item.get('shazam_id', ShazamStatus.PENDING) == ShazamStatus.PENDING:
        return
    media.remove_local_files(item)
    db.videos().update_one({'vid': vid, 'dstatus': DStatus.LOCAL}, {'$set': {'dstatus': DStatus.CLOUD}})
    logger.info('已归档：%s %s', item['title'], vid)
