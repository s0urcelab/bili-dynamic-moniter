import os
from dotenv import load_dotenv

load_dotenv()

DYNAMIC_COOKIE = os.environ['FO_COOKIE']
DOWNLOAD_COOKIE = os.environ['DL_COOKIE']
DB_PATH = os.environ['DB_PATH']
MEDIA_ROOT = os.environ['MEDIA_ROOT']
MAX_DYNAMIC_FETCH_PAGE = int(os.environ['MAX_DYNAMIC_FETCH_PAGE'])
CONCURRENT_TASK_NUM = int(os.environ['CONCURRENT_TASK_NUM'])