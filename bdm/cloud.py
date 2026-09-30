import logging
import threading

from bdm import config

logger = logging.getLogger(__name__)

_client = None
_lock = threading.Lock()


def client():
    """延迟登录，避免进程启动时就依赖云盘可用。"""
    global _client
    with _lock:
        if _client is None:
            from cloud189 import Cloud189

            config.require('CLOUD189_USERNAME', 'CLOUD189_PASSWORD')
            _client = Cloud189({
                'username': config.CLOUD189_USERNAME,
                'password': config.CLOUD189_PASSWORD,
            })
        return _client


def reset():
    global _client
    with _lock:
        _client = None


def upload(path, name):
    config.require('CLOUD189_TARGET_FOLDER_ID')
    return client().upload(path, config.CLOUD189_TARGET_FOLDER_ID, name)


def play_url(fid):
    return client().get_play_url(fid)


def disk_usage():
    info = client().get_disk_space_info()['cloudCapacityInfo']
    return info['usedSize'], info['totalSize']


def delete_files(vid, fid=None, cover_fid=None):
    """删除云盘上的视频和封面，单个文件失败不影响其他文件。"""
    targets = []
    if fid:
        targets.append((fid, f'{vid}.mp4'))
    if cover_fid:
        targets += [(cover_fid, f'{vid}.jpg'), (cover_fid, f'{vid}.png')]
    for fid, name in targets:
        try:
            client().delete(fid, name)
        except Exception as err:
            logger.warning('删除云盘文件失败 %s：%s', name, err)


def delete_video_files(item):
    """删除稿件在云盘上的所有文件，包括被新版本替换、尚未清理的旧版本。"""
    delete_files(item['vid'], item.get('fid'), item.get('cover_fid'))
    delete_files(item['vid'], item.get('stale_fid'), item.get('stale_cover_fid'))
