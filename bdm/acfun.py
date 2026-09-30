import json
import re

from bdm.net import TIMEOUT, make_session

_PAGE_INFO_RE = re.compile(r'window\.pageInfo\s*=\s*window\.videoInfo\s*=\s*(\{(?:(?<!\};).)*\});')


class AcfunError(Exception):
    pass


def video_url(acid, p=1):
    return f'https://www.acfun.cn/v/{acid}_{p}'


def video_meta(acid, p=1):
    res = make_session().get(video_url(acid, p), timeout=TIMEOUT)
    res.raise_for_status()
    match = _PAGE_INFO_RE.search(res.text)
    if not match:
        raise AcfunError(f'解析 {acid} 页面失败')
    info = json.loads(match.group(1))

    parts = info.get('videoList') or []
    if not 1 <= p <= len(parts):
        raise AcfunError(f'{acid} 不存在第 {p} P')
    part = parts[p - 1]
    current = info.get('currentVideoInfo') or {}
    transcodes = current.get('transcodeInfos') or [{}]

    return {
        'title': info['title'],
        'desc': info.get('description', ''),
        'cover': info.get('coverUrl', ''),
        'uid': int(info['user']['id']),
        'uname': info['user']['name'],
        'avatar': info['user'].get('headUrl', ''),
        'p_title': part.get('title', ''),
        'duration': int(part.get('durationMillis', 0)) // 1000,
        'is_portrait': 1 if int(current.get('sizeType', 1)) == 2 else 0,
        'max_quality': (transcodes[0].get('qualityType') or '未知').upper(),
    }
