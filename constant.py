import os
from dotenv import load_dotenv

load_dotenv()

DYNAMIC_COOKIE = os.environ['FO_COOKIE']
DOWNLOAD_COOKIE = os.environ['DL_COOKIE']
DL_COOKIE_FILE = os.environ['DL_COOKIE_FILE']
MEDIA_ROOT = os.environ['MEDIA_ROOT']
MAX_DYNAMIC_FETCH_PAGE = int(os.environ['MAX_DYNAMIC_FETCH_PAGE'])
CONCURRENT_TASK_NUM = int(os.environ['CONCURRENT_TASK_NUM'])
MONGODB_URL = os.environ['MONGODB_URL']

USER_DYNAMIC_API = lambda page,offset: f'https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all?timezone_offset=-480&type=video&page={page}&features=itemOpusStyle&offset={offset}'
USER_FOLLOW_API = lambda page: f'https://api.bilibili.com/x/relation/tag?mid=543741&tagid=37444368&pn={page}&ps=20'
VIDEO_DETAIL_API = lambda bvid, p=1: f'https://www.bilibili.com/video/{bvid}?p={p}'
VIDEO_VIEW_API = lambda bvid: f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}'

ACFUN_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.74 Safari/537.36 Edg/99.0.1150.52'
ACFUN_VIDEO_PLAY_API = lambda acid, p=1: f'https://www.acfun.cn/v/{acid}_{p}'
