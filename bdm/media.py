"""
本地媒体文件的命名与查找。文件名规则沿用历史数据：
    source=0          bilix 下载，   {标题}*.mp4
    source=1/2/3      yt-dlp 下载，  {标题}-{vid}.mp4
    source=其他字符串  本地手动下载，  *{source}*.mp4
"""
import glob
import html
import json
import logging
import os
import re
import shutil
import subprocess
from urllib.parse import quote

from bdm import config
from bdm.status import Source

logger = logging.getLogger(__name__)

COVER_EXTS = ('.jpg', '.png', '.jpeg', '.gif', '.webp')


def _clean(s):
    s = html.unescape(s.strip())
    return re.sub(r'[/\\:*?"<>|\n]', '', s)


def safe_title(title, limit=60):
    title = _clean(title)
    return title if len(title) <= limit else title[:limit - 3] + '...'


def output_template(item, directory=None):
    return os.path.join(directory or config.MEDIA_ROOT, f'{safe_title(item["title"])}-{item["vid"]}.%(ext)s')


def incoming_dir(item):
    """新版本先下载到这里，确认可用后才替换 MEDIA_ROOT 中的旧文件。"""
    return os.path.join(config.MEDIA_ROOT, '.incoming', _clean(item['vid']))


def prepare_incoming(item):
    path = incoming_dir(item)
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)
    return path


def discard_incoming(item):
    shutil.rmtree(incoming_dir(item), ignore_errors=True)


def incoming_video(item):
    files = glob.glob(os.path.join(glob.escape(incoming_dir(item)), '*.mp4'))
    return files[0] if files else None


def promote_incoming(item):
    """用临时目录中的新版本替换本地旧文件，返回新视频的路径。"""
    for path in {*video_files(item), *cover_files(item)}:
        _remove(path)
    src_dir = incoming_dir(item)
    for name in os.listdir(src_dir):
        if name.endswith('.mp4') or name.endswith(COVER_EXTS):
            os.replace(os.path.join(src_dir, name), os.path.join(config.MEDIA_ROOT, name))
    discard_incoming(item)
    files = video_files(item)
    return files[0] if files else None


def _glob(pattern):
    return glob.glob(os.path.join(config.MEDIA_ROOT, pattern))


def video_files(item):
    source = item.get('source')
    if source == Source.BILIX:
        return _glob(f'{glob.escape(_clean(item["title"][:30]))}*.mp4')
    if source in (Source.IMPORT_BILI, Source.DYNAMIC, Source.IMPORT_ACFUN):
        return _glob(f'*-{glob.escape(item["vid"])}.mp4')
    return _glob(f'*{glob.escape(str(source))}*.mp4')


def cover_files(item):
    source = item.get('source')
    if source == Source.BILIX:
        prefix = glob.escape(_clean(item['title'][:30]))
        return [f for ext in COVER_EXTS for f in _glob(f'{prefix}*{ext}')]
    if source in (Source.IMPORT_BILI, Source.DYNAMIC, Source.IMPORT_ACFUN):
        vid = glob.escape(item['vid'])
        return [f for ext in COVER_EXTS for f in _glob(f'*-{vid}{ext}')]
    return [f for ext in COVER_EXTS for f in _glob(f'*{glob.escape(str(source))}*{ext}')]


def fragment_files(item):
    vid = glob.escape(item['vid'])
    return _glob(f'*-{vid}.f[0-9]*') + _glob(f'*-{vid}.*.part') + _glob(f'*-{vid}.temp.*')


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as err:
        logger.warning('删除本地文件失败 %s：%s', path, err)


def remove_fragments(item):
    for path in fragment_files(item):
        _remove(path)


def remove_local_files(item):
    for path in {*fragment_files(item), *video_files(item), *cover_files(item)}:
        _remove(path)
    discard_incoming(item)


def local_url(path):
    if not config.LOCAL_FILE_URL_PREFIX:
        return None
    rel = os.path.relpath(path, config.MEDIA_ROOT).replace(os.sep, '/')
    return config.LOCAL_FILE_URL_PREFIX.rstrip('/') + '/' + quote(rel)


def probe_video(path):
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,bit_rate,r_frame_rate', '-of', 'json', path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
    stream = json.loads(result.stdout)['streams'][0]
    num, den = map(int, stream.get('r_frame_rate', '0/1').split('/'))
    bit_rate = stream.get('bit_rate')
    return {
        'width': int(stream['width']),
        'height': int(stream['height']),
        'bitrate': int(bit_rate) if bit_rate and bit_rate.isdigit() else 0,
        'fps': round(num / den, 2) if den else 0,
    }


def dir_size(path=None):
    total = 0
    with os.scandir(path or config.MEDIA_ROOT) as it:
        for entry in it:
            if entry.is_file(follow_symlinks=False):
                total += entry.stat().st_size
            elif entry.is_dir(follow_symlinks=False):
                total += dir_size(entry.path)
    return total
