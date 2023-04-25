# -*- coding: utf-8 -*-

import sys
import os
import re
import requests
import json
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
from util import match_bgm
from tinydb import TinyDB, Query, where

# 加载.env的环境变量
load_dotenv()
# 配置logger
logger = logging.getLogger()

DB_PATH = os.environ['DB_PATH']
CONCURRENT_TASK_NUM = int(os.environ['CONCURRENT_TASK_NUM'])

db = TinyDB(DB_PATH)
config = db.table('config')
dynamic_list = db.table('dynamic_list', cache_size=0)

# async task
async def async_task():
    q_sz = (where('shazam_id') == 0) & (where('dstatus') == 200)
    wait_match_list = sorted(dynamic_list.search(q_sz), key=lambda i: i['pdate'], reverse=True)[:CONCURRENT_TASK_NUM]
    await match_bgm(wait_match_list, logger.warning)

if __name__ == '__main__':
    logger.info('定时任务：开始匹配bgm')
    asyncio.get_event_loop().run_until_complete(async_task())
