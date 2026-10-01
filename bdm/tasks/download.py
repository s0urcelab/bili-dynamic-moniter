"""下载待处理的稿件并校验分辨率，成功后状态变为 LOCAL，交给 upload / match 阶段。"""
import logging
import os
from datetime import datetime, timezone

from yt_dlp import YoutubeDL

from bdm import config, cookies, db, media, videos
from bdm.status import DStatus, ShazamStatus, UStatus
from bdm.tasks import state

logger = logging.getLogger(__name__)

STAGE = 'download'


class DownloadError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class _YtdlpLogger:
    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        logger.error(msg)


def candidates(limit):
    in_range = 'duration > ? AND duration < ?'
    in_range_args = (config.DOWNLOAD_MIN_DURATION, config.DOWNLOAD_MAX_DURATION)
    selected = f'ustatus >= {UStatus.SELECTED}'
    requested = 'dl_requested = 1'  # 后台手动要求重新下载，不受时长限制
    non_retryable = ', '.join(str(s) for s in DStatus.NON_RETRYABLE)
    retryable = f'dstatus < 0 AND dstatus NOT IN ({non_retryable}) AND dl_retry < ?'
    queries = [
        (f'dstatus = {DStatus.DOWNLOADING}', ()),  # 上一轮被中断
        (f'({selected} OR {requested}) AND dstatus = {DStatus.PENDING}', ()),
        (f'{in_range} AND dstatus = {DStatus.PENDING}', in_range_args),
        (f'({selected} OR ({in_range}) OR {requested}) AND {retryable}',
         (*in_range_args, config.MAX_DOWNLOAD_RETRY)),
    ]
    picked, seen = [], set()
    for where, params in queries:
        for item in db.find_videos(where, params, limit=limit):
            if item['vid'] not in seen:
                seen.add(item['vid'])
                picked.append(item)
            if len(picked) >= limit:
                return picked
    return picked


def ydl_options(item, directory, cookiefile=None):
    opts = {
        'outtmpl': media.output_template(item, directory),
        'format_sort': ['size'],
        'merge_output_format': 'mp4',
        'writethumbnail': True,
        'postprocessors': [{'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg', 'when': 'before_dl'}],
        'updatetime': False,
        'noprogress': True,
        'quiet': True,
        'socket_timeout': 30,
        'retries': 5,
        'logger': _YtdlpLogger(),
    }
    if cookiefile:
        opts['cookiefile'] = cookiefile
    return opts


def quality_ok(max_quality, info):
    quality = (max_quality or '').upper()
    longest = max(info['width'], info['height'])
    if '4K' in quality or '2160P' in quality:
        return longest > 1920
    if '1080P' in quality:
        return longest > 1080
    return True


def _longest(info):
    return max(info['width'], info['height']) if info else 0


def _describe(info):
    return f'{info["width"]}x{info["height"]}' if info else '未知'


def existing_version(item):
    """本地已有的完整版本（上次分辨率不达标被保留，或尚未归档的文件）及其分辨率。"""
    files = media.video_files(item)
    if not files:
        return None, None
    info = item.get('video_info')
    if not info:
        try:
            info = media.probe_video(files[0])
        except Exception as err:
            logger.warning('无法读取本地已有文件的分辨率 %s：%s', item['vid'], err)
    return files[0], info


def _mark_local(item, info, low_res, extra_set=None, extra_unset=(), inc_retry=False):
    db.update_videos(
        'vid = ?', (item['vid'],),
        set={
            'dstatus': DStatus.LOCAL, 'video_info': info, 'low_res': low_res,
            'downloaded_at': datetime.now(timezone.utc), **(extra_set or {}),
        },
        unset=[*extra_unset, 'dl_requested'],
        inc={'dl_retry': 1} if inc_retry else None,
    )
    db.update_videos(f'vid = ? AND bgm_status = {ShazamStatus.NO_FILE}', (item['vid'],),
                     set={'shazam_id': ShazamStatus.PENDING})
    videos.finalize(item['vid'])


def _on_downloaded(item, old_path, old_info, new_info, exhausted):
    vid = item['vid']
    max_quality = item.get('max_quality')
    replace = old_path is None or quality_ok(max_quality, new_info) or _longest(new_info) >= _longest(old_info)

    fields, unset = {}, ['dl_error']
    if replace:
        media.promote_incoming(item)
        info = new_info
        # 云盘上的旧版本在新版本上传前删除
        if item.get('fid') or item.get('cover_fid'):
            fields.update({'stale_fid': item.get('fid'), 'stale_cover_fid': item.get('cover_fid')})
            unset += ['fid', 'cover_fid']
    else:
        media.discard_incoming(item)
        info = old_info
        logger.info('新版本 %s 不如本地已有版本 %s，保留旧文件：%s', _describe(new_info), _describe(old_info), vid)

    low_res = not quality_ok(max_quality, info)
    if low_res and not exhausted:
        message = f'分辨率不达标：{_describe(info)}，稿件最高画质 {max_quality}（已保留本地文件，等待重试）'
        unset.remove('dl_error')
        db.update_videos('vid = ?', (vid,),
                         set={**fields, 'dstatus': DStatus.LOW_RES, 'video_info': info, 'dl_error': message},
                         unset=unset, inc={'dl_retry': 1})
        logger.warning('%s：%s', message, vid)
        return message

    if low_res:
        logger.warning('分辨率仍不达标，已达重试上限，使用当前最好的版本 %s：%s', _describe(info), vid)
    _mark_local(item, info, low_res, fields, unset)
    logger.info('下载成功：%s %s', item['title'], vid)
    return None


def _on_failed(item, code, message, old_path, old_info, exhausted):
    vid = item['vid']
    if exhausted and old_path:
        # 稿件可能已被删除，保留上次下载的版本继续后续流程
        low_res = not quality_ok(item.get('max_quality'), old_info) if old_info else False
        _mark_local(item, old_info, low_res, {'dl_error': message[:500]}, inc_retry=True)
        logger.warning('下载失败且重试已用尽，保留本地已有版本：%s', vid)
        return message
    if exhausted and item.get('fid'):
        db.update_videos('vid = ?', (vid,), set={'dstatus': DStatus.CLOUD, 'dl_error': message[:500]},
                         unset=['dl_requested'], inc={'dl_retry': 1})
        logger.warning('下载失败且重试已用尽，保留云盘已有版本：%s', vid)
        return message

    db.update_videos('vid = ?', (vid,), set={'dstatus': code, 'dl_error': message[:500]},
                     unset=['dl_requested'] if exhausted else (), inc={'dl_retry': 1})
    logger.error('下载失败[%s]：%s %s%s', message, item['title'], vid, '（本地已有版本保留）' if old_path else '')
    return message


def download_one(item, cookiefile=None):
    """
    新版本先下载到临时目录，确认可用后才替换本地旧文件；下载失败时本地文件保持不动。
    返回 None 表示成功，否则返回错误信息。
    """
    vid = item['vid']
    exhausted = item.get('dl_retry', 0) + 1 >= config.MAX_DOWNLOAD_RETRY
    logger.info('开始下载：%s %s', item['title'], vid)
    db.update_videos('vid = ?', (vid,), set={'dstatus': DStatus.DOWNLOADING})
    media.remove_fragments(item)
    old_path, old_info = existing_version(item)

    try:
        directory = media.prepare_incoming(item)
        with YoutubeDL(ydl_options(item, directory, cookiefile)) as ydl:
            ydl.download([videos.download_url(item)])
        new_path = media.incoming_video(item)
        if not new_path:
            raise DownloadError('下载完成但找不到视频文件', DStatus.FILE_MISSING)
        new_info = media.probe_video(new_path)
    except DownloadError as err:
        code, message = err.code, str(err)
    except Exception as err:
        logger.exception('下载异常：%s', vid)
        code, message = DStatus.FAILED, str(err)
    else:
        return _on_downloaded(item, old_path, old_info, new_info, exhausted)

    media.discard_incoming(item)
    return _on_failed(item, code, message, old_path, old_info, exhausted)


def cookie_ready():
    """cookie 明确失效时暂停本阶段，避免以未登录画质下载而浪费重试次数。网络异常时不拦截。"""
    login = cookies.check('download')
    if login['logged_in'] is False:
        reason = f'{cookies.PAUSE_REASON_PREFIX}（{login.get("error") or "未登录"}），更新后会自动恢复'
        state.pause(STAGE, reason)
        state.report_error(STAGE, reason)
        logger.error(reason)
        return False
    if login['logged_in'] and not login.get('vip'):
        logger.warning('下载 cookie 对应账号 %s 不是大会员，部分高画质可能无法下载', login.get('uname'))
    return True


def run():
    items = candidates(config.DOWNLOAD_BATCH)
    if not items:
        return '没有待下载的稿件'
    if not cookie_ready():
        return '下载 cookie 已失效，已暂停下载'

    cookiefile = cookies.download_cookiefile()
    ok = failed = 0
    try:
        for item in items:
            if not state.is_enabled(STAGE):
                logger.info('下载已被关闭，停止本轮')
                break
            error = download_one(item, cookiefile)
            if error is None:
                ok += 1
            else:
                failed += 1
                state.report_error(STAGE, error, f'[{item["vid"]}] {item["title"]}')
    finally:
        if cookiefile and cookiefile != config.DL_COOKIE_FILE:
            os.remove(cookiefile)
    return f'下载成功 {ok} 个，失败 {failed} 个'
