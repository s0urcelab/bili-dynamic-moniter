import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _str(name, default=''):
    return os.environ.get(name, default)


def _int(name, default):
    value = os.environ.get(name)
    return int(value) if value not in (None, '') else default


def _bool(name, default):
    value = os.environ.get(name)
    if value in (None, ''):
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def require(*names):
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise RuntimeError(f'缺少环境变量：{", ".join(missing)}')


TZ = ZoneInfo(_str('TZ', 'Asia/Shanghai'))
LOG_LEVEL = _str('LOG_LEVEL', 'INFO')

# 存储
MONGODB_URL = _str('MONGODB_URL')
MONGODB_DB = _str('MONGODB_DB', 'dance')
MEDIA_ROOT = _str('MEDIA_ROOT', '/media')
LOCAL_FILE_URL_PREFIX = _str('LOCAL_FILE_URL_PREFIX')

# API
JWT_SECRET_KEY = _str('JWT_SECRET_KEY')
JWT_COOKIE_SECURE = _bool('JWT_COOKIE_SECURE', True)
MANAGE_PASSWORD = _str('MANAGE_PASSWORD')

# B站
BILI_SESSDATA = _str('FO_COOKIE')
BILI_MID = _int('BILI_MID', 543741)
BILI_FOLLOW_TAG_ID = _int('BILI_FOLLOW_TAG_ID', 37444368)
DL_COOKIE_FILE = _str('DL_COOKIE_FILE')
MAX_DYNAMIC_FETCH_PAGE = _int('MAX_DYNAMIC_FETCH_PAGE', 10)

# 天翼云盘
CLOUD189_USERNAME = _str('CLOUD189_USERNAME')
CLOUD189_PASSWORD = _str('CLOUD189_PASSWORD')
CLOUD189_TARGET_FOLDER_ID = _str('CLOUD189_TARGET_FOLDER_ID')

# 流水线
DOWNLOAD_BATCH = _int('DOWNLOAD_BATCH', _int('CONCURRENT_TASK_NUM', 3))
UPLOAD_BATCH = _int('UPLOAD_BATCH', 5)
MATCH_BATCH = _int('MATCH_BATCH', _int('CONCURRENT_TASK_NUM', 3))
DOWNLOAD_MIN_DURATION = _int('DOWNLOAD_MIN_DURATION', 20)
DOWNLOAD_MAX_DURATION = _int('DOWNLOAD_MAX_DURATION', 600)
MAX_DOWNLOAD_RETRY = _int('MAX_DOWNLOAD_RETRY', 3)
MAX_UPLOAD_RETRY = _int('MAX_UPLOAD_RETRY', 3)
UPLOAD_PAUSE_THRESHOLD = _int('UPLOAD_PAUSE_THRESHOLD', 3)

# 调度（单位：分钟）
SCHEDULE = {
    'fetch': {'interval': _int('FETCH_INTERVAL', 15), 'timeout': _int('FETCH_TIMEOUT', 10)},
    'download': {'interval': _int('DOWNLOAD_INTERVAL', 2), 'timeout': _int('DOWNLOAD_TIMEOUT', 60)},
    'upload': {'interval': _int('UPLOAD_INTERVAL', 1), 'timeout': _int('UPLOAD_TIMEOUT', 120)},
    'match': {'interval': _int('MATCH_INTERVAL', 5), 'timeout': _int('MATCH_TIMEOUT', 30)},
}
