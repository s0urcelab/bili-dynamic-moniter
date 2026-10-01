from datetime import datetime

from bdm import config
from bdm.net import TIMEOUT, make_session

FOLLOW_TAG_API = 'https://api.bilibili.com/x/relation/tag'
FEED_API = 'https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all'
VIEW_API = 'https://api.bilibili.com/x/web-interface/view'
PLAYURL_API = 'https://api.bilibili.com/x/player/wbi/playurl'
NAV_API = 'https://api.bilibili.com/x/web-interface/nav'

SPECIAL_FOLLOW_TAG_ID = -10
FOLLOW_PAGE_SIZE = 30


class BiliError(Exception):
    pass


def video_url(bvid, p=1):
    return f'https://www.bilibili.com/video/{bvid}?p={p}'


def parse_duration_text(text):
    total = 0
    for part in (text or '').split(':'):
        if not part.isdigit():
            return 0
        total = total * 60 + int(part)
    return total


def format_ts(ts):
    return datetime.fromtimestamp(ts, config.TZ).strftime('%Y-%m-%d %H:%M:%S')


def parse_feed_item(item):
    """把动态流中的一条视频动态转成稿件的基础字段；非视频动态返回 None。"""
    try:
        author = item['modules']['module_author']
        archive = item['modules']['module_dynamic']['major']['archive']
        pdate = int(author['pub_ts'])
        return {
            'uid': author['mid'],
            'uname': author['name'],
            'avatar': author['face'],
            'pdate': pdate,
            'pdstr': format_ts(pdate),
            'vid': archive['bvid'],
            'title': archive['title'],
            'cover': archive.get('cover', ''),
            'desc': archive.get('desc', ''),
            'duration_text': archive.get('duration_text', ''),
            'duration': parse_duration_text(archive.get('duration_text')),
        }
    except (KeyError, TypeError, ValueError):
        return None


class BiliAuthError(BiliError):
    pass


NOT_LOGGED_IN = -101


class BiliClient:
    def __init__(self, cookies=None):
        self.session = make_session(referer='https://www.bilibili.com/')
        self.cookies = cookies or None

    def _get(self, url, params=None, auth=False):
        res = self.session.get(url, params=params, cookies=self.cookies if auth else None, timeout=TIMEOUT)
        res.raise_for_status()
        body = res.json()
        if body.get('code') == NOT_LOGGED_IN:
            raise BiliAuthError('B站 cookie 未登录或已失效，请在管理后台更新订阅 cookie')
        if body.get('code') != 0:
            raise BiliError(f'{url} 返回 code={body.get("code")} {body.get("message", "")}')
        return body.get('data')

    def nav(self):
        """当前 cookie 对应的登录信息；未登录时 logged_in 为 False。"""
        try:
            data = self._get(NAV_API, auth=True) or {}
        except BiliAuthError:
            return {'logged_in': False}
        return {
            'logged_in': bool(data.get('isLogin')),
            'uid': data.get('mid'),
            'uname': data.get('uname'),
            'vip': data.get('vipStatus') == 1,
        }

    def tag_members(self, tag_id, max_pages=100):
        members = []
        for pn in range(1, max_pages + 1):
            params = {'mid': config.BILI_MID, 'tagid': tag_id, 'pn': pn, 'ps': FOLLOW_PAGE_SIZE}
            page = self._get(FOLLOW_TAG_API, params, auth=True) or []
            members.extend(page)
            if len(page) < FOLLOW_PAGE_SIZE:
                break
        return members

    def feed_page(self, page, offset=''):
        params = {
            'timezone_offset': -480,
            'type': 'video',
            'page': page,
            'features': 'itemOpusStyle',
            'offset': offset,
        }
        data = self._get(FEED_API, params, auth=True) or {}
        return data.get('items') or [], data.get('offset', ''), bool(data.get('has_more'))

    def video_meta(self, bvid, p=1):
        view = self._get(VIEW_API, {'bvid': bvid})
        pages = view.get('pages') or []
        if not 1 <= p <= len(pages):
            raise BiliError(f'{bvid} 不存在第 {p} P')
        page = pages[p - 1]
        cid = page['cid']
        play = self._get(PLAYURL_API, {'bvid': bvid, 'cid': cid, 'fnval': 4048})

        dim = page.get('dimension') or view.get('dimension') or {}
        width, height = dim.get('width') or 0, dim.get('height') or 0
        if dim.get('rotate'):
            width, height = height, width
        timelength = play.get('timelength')

        return {
            'cid': cid,
            'title': view['title'],
            'desc': view.get('desc', ''),
            'cover': view.get('pic', ''),
            'uid': view['owner']['mid'],
            'uname': view['owner']['name'],
            'avatar': view['owner']['face'],
            'p_title': page.get('part', ''),
            'duration': round(timelength / 1000) if timelength else page.get('duration', 0),
            'is_portrait': 1 if width and height and width < height else 0,
            'max_quality': (play.get('accept_description') or ['未知'])[0],
            'is_paid': bool(view.get('is_upower_exclusive')),
        }
