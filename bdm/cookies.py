"""
B站 cookie 管理。两类 cookie 优先使用管理后台保存在数据库中的值，未配置时回退到环境变量：

    subscribe  读取关注分组与动态流      回退 FO_COOKIE（SESSDATA 值）
    download   yt-dlp 下载时使用        回退 DL_COOKIE_FILE（Netscape cookies.txt 路径）

保存时接受三种格式：单独的 SESSDATA 值、"name=value; ..." 形式的请求头、Netscape cookies.txt 内容。
"""
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from urllib.parse import unquote

from bdm import config, db
from bdm.bilibili import BiliClient

logger = logging.getLogger(__name__)

KINDS = ('subscribe', 'download')
KIND_LABELS = {'subscribe': '订阅 cookie', 'download': '下载 cookie'}

NETSCAPE_HEADER = '# Netscape HTTP Cookie File'
BILI_DOMAIN = '.bilibili.com'
DEFAULT_LIFETIME = 180 * 86400

# 下载阶段因 cookie 失效而自动暂停时使用的原因前缀，更新 cookie 且检测通过后据此自动恢复
PAUSE_REASON_PREFIX = '下载 cookie 已失效'


class CookieError(ValueError):
    pass


def _setting_key(kind):
    return f'cookie_{kind}'


def _check_key(kind):
    return f'cookie_check_{kind}'


# ---------- 解析 ----------

def detect_format(text):
    if '\t' in text or text.lstrip().startswith('#') or '\n' in text.strip():
        return 'netscape'
    if '=' in text:
        return 'header'
    return 'sessdata'


def parse(text):
    """解析为 [{domain, name, value, expires}]，expires 为 0 表示未知。"""
    text = (text or '').strip()
    if not text:
        raise CookieError('cookie 内容为空')
    fmt = detect_format(text)

    if fmt == 'sessdata':
        return [{'domain': BILI_DOMAIN, 'name': 'SESSDATA', 'value': text, 'expires': 0}]

    if fmt == 'header':
        result = []
        for part in text.removeprefix('Cookie:').split(';'):
            name, sep, value = part.strip().partition('=')
            if sep and name:
                result.append({'domain': BILI_DOMAIN, 'name': name.strip(), 'value': value.strip(), 'expires': 0})
        if not result:
            raise CookieError('无法解析 cookie，格式应为 name=value; name2=value2')
        return result

    result = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('#HttpOnly_'):
            line = line[len('#HttpOnly_'):]
        elif not line or line.startswith('#'):
            continue
        fields = line.split('\t') if '\t' in line else line.split(None, 6)
        if len(fields) != 7:
            raise CookieError(f'无法解析 cookies.txt 中的这一行：{line[:80]}')
        domain, _, _, _, expires, name, value = fields
        result.append({
            'domain': domain, 'name': name, 'value': value,
            'expires': int(expires) if expires.isdigit() else 0,
        })
    if not result:
        raise CookieError('cookies.txt 中没有有效的 cookie')
    return result


def sessdata_expiry(value):
    """SESSDATA 形如 "xxx,1735689600,xxx"（通常经过 URL 编码），第二段为过期时间。"""
    parts = unquote(value).split(',')
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return 0


def _is_bili(domain):
    return domain.lstrip('.').endswith('bilibili.com')


def bili_cookies(records):
    return {r['name']: r['value'] for r in records if _is_bili(r['domain'])}


def expires_at(records):
    for r in records:
        if r['name'] == 'SESSDATA' and _is_bili(r['domain']):
            ts = r['expires'] or sessdata_expiry(r['value'])
            return datetime.fromtimestamp(ts, timezone.utc) if ts else None
    return None


def to_netscape(records):
    fallback = int(time.time()) + DEFAULT_LIFETIME
    lines = [NETSCAPE_HEADER]
    for r in records:
        expires = r['expires'] or sessdata_expiry(r['value']) or fallback
        include_sub = 'TRUE' if r['domain'].startswith('.') else 'FALSE'
        lines.append('\t'.join([r['domain'], include_sub, '/', 'TRUE', str(expires), r['name'], r['value']]))
    return '\n'.join(lines) + '\n'


# ---------- 读取 ----------

def _stored(kind):
    return db.get_setting(_setting_key(kind))


def _env_text(kind):
    if kind == 'subscribe':
        return config.BILI_SESSDATA or None
    path = config.DL_COOKIE_FILE
    if path and os.path.isfile(path):
        with open(path, encoding='utf-8') as f:
            return f.read()
    return None


def load(kind):
    """返回 (解析后的 cookie 列表, 来源)；未配置时返回 (None, None)。"""
    stored = _stored(kind)
    if stored and stored.get('content'):
        return parse(stored['content']), 'admin'
    text = _env_text(kind)
    if text:
        return parse(text), 'env'
    return None, None


def subscribe_cookies():
    records, _ = load('subscribe')
    if not records:
        raise CookieError('未配置订阅 cookie，请在管理后台设置')
    return bili_cookies(records)


def download_cookiefile():
    """为本次下载进程写出临时 cookies.txt，返回路径；未配置时返回 None。"""
    records, source = load('download')
    if not records:
        return None
    if source == 'env' and detect_format(_env_text('download')) == 'netscape':
        return config.DL_COOKIE_FILE
    fd, path = tempfile.mkstemp(prefix='bdm-cookies-', suffix='.txt')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(to_netscape(records))
    return path


# ---------- 写入与检测 ----------

def save(kind, text):
    records = parse(text)
    if not bili_cookies(records).get('SESSDATA'):
        raise CookieError('cookie 中没有 bilibili.com 的 SESSDATA')
    db.set_setting(_setting_key(kind), {
        'content': text.strip(),
        'format': detect_format(text.strip()),
        'updated_at': datetime.now(timezone.utc),
    })


def clear(kind):
    db.settings().delete_many({_setting_key(kind): {'$exists': True}})
    db.settings().delete_many({_check_key(kind): {'$exists': True}})


def check(kind):
    """用 cookie 请求 B站 nav 接口，记录并返回登录状态。网络错误时 logged_in 为 None。"""
    result = {'checked_at': datetime.now(timezone.utc), 'logged_in': None, 'error': None}
    try:
        records, _ = load(kind)
        if not records:
            result.update({'logged_in': False, 'error': '未配置'})
        else:
            result.update(BiliClient(bili_cookies(records)).nav())
    except CookieError as err:
        result.update({'logged_in': False, 'error': str(err)})
    except Exception as err:
        logger.warning('检测%s失败：%s', KIND_LABELS[kind], err)
        result['error'] = f'检测失败：{err}'
    db.set_setting(_check_key(kind), result)
    return result


def describe(kind):
    """后台展示用的摘要，不包含 cookie 值。"""
    info = {
        'kind': kind,
        'label': KIND_LABELS[kind],
        'configured': False,
        'source': None,
        'format': None,
        'names': [],
        'domains': [],
        'expires_at': None,
        'updated_at': None,
        'last_check': db.get_setting(_check_key(kind)),
        'error': None,
    }
    try:
        records, source = load(kind)
    except CookieError as err:
        info['error'] = str(err)
        return info
    if not records:
        return info
    stored = _stored(kind) if source == 'admin' else None
    info.update({
        'configured': True,
        'source': source,
        'format': stored['format'] if stored else detect_format(_env_text(kind)),
        'names': sorted({r['name'] for r in records}),
        'domains': sorted({r['domain'] for r in records}),
        'expires_at': expires_at(records),
        'updated_at': stored['updated_at'] if stored else None,
    })
    return info
