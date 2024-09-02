import os
from dotenv import load_dotenv

load_dotenv()

JWT_SECRET_KEY = os.environ['JWT_SECRET_KEY']
DYNAMIC_COOKIE = os.environ['FO_COOKIE']
DL_COOKIE_FILE = os.environ['DL_COOKIE_FILE']
MEDIA_ROOT = os.environ['MEDIA_ROOT']
MAX_DYNAMIC_FETCH_PAGE = int(os.environ['MAX_DYNAMIC_FETCH_PAGE'])
CONCURRENT_TASK_NUM = int(os.environ['CONCURRENT_TASK_NUM'])
MONGODB_URL = os.environ['MONGODB_URL']
MANAGE_PASSWORD = os.environ['MANAGE_PASSWORD']
CLOUD189_USERNAME = os.environ['CLOUD189_USERNAME']
CLOUD189_PASSWORD = os.environ['CLOUD189_PASSWORD']
CLOUD189_TARGET_FOLDER_ID = os.environ['CLOUD189_TARGET_FOLDER_ID']

USER_DYNAMIC_API = lambda page,offset: f'https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all?timezone_offset=-480&type=video&page={page}&features=itemOpusStyle&offset={offset}'
USER_FOLLOW_API = lambda page: f'https://api.bilibili.com/x/relation/tag?mid=543741&tagid=37444368&pn={page}&ps=20'
VIDEO_DETAIL_API = lambda bvid, p=1: f'https://www.bilibili.com/video/{bvid}?p={p}'
VIDEO_VIEW_API = lambda bvid: f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}'

FAKE_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.74 Safari/537.36 Edg/99.0.1150.52'
ACFUN_VIDEO_PLAY_API = lambda acid, p=1: f'https://www.acfun.cn/v/{acid}_{p}'

class DSTATUS:
    DEFAULT = 0
    DOWNLOADING = 100
    LOCAL = 200
    CLOUD189 = 201
    
class USTATUS:
    DEFAULT = 0
    SELECTED = 100
    UPLOADED = 200
