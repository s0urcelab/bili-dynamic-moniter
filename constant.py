import os
from dotenv import load_dotenv

load_dotenv()

DYNAMIC_COOKIE = os.environ['FO_COOKIE']
DOWNLOAD_COOKIE = os.environ['DL_COOKIE']
DL_COOKIE_FILE = os.environ['DL_COOKIE_FILE']
DB_PATH = os.environ['DB_PATH']
MEDIA_ROOT = os.environ['MEDIA_ROOT']
MAX_DYNAMIC_FETCH_PAGE = int(os.environ['MAX_DYNAMIC_FETCH_PAGE'])
CONCURRENT_TASK_NUM = int(os.environ['CONCURRENT_TASK_NUM'])

USER_DYNAMIC_API = lambda page,offset: f'https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all?timezone_offset=-480&type=video&page={page}&features=itemOpusStyle&offset={offset}'
USER_FOLLOW_API = lambda page: f'https://api.bilibili.com/x/relation/tag?mid=543741&tagid=37444368&pn={page}&ps=20'
VIDEO_DETAIL_API = lambda bvid: f'https://www.bilibili.com/video/{bvid}'
VIDEO_VIEW_API = lambda bvid: f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}'