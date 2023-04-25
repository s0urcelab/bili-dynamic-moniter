# -*- coding: utf-8 -*-

import sys
import os
import requests
import json
import glob
import asyncio
import html
import re
from datetime import datetime
from tinydb import TinyDB, Query, where
from bilix.sites.bilibili import DownloaderBilibili
from pathlib import Path
# from util import download_video
from flask import Flask, flash, request, render_template

DB_PATH = './db.json'
DB_PATH2 = './db.json.bak'

db = TinyDB(DB_PATH)
db2 = TinyDB(DB_PATH2)
config = db.table('config')
shazam_list = db.table('shazam_list')
dynamic_list = db.table('dynamic_list')
dynamic_list2 = db2.table('dynamic_list')

# dynamic_list.update({'dstatus': 0}, where('bvid').one_of(['BV12j411F7Dm', 'BV1wv4y1W75d', 'BV1ds4y1J7qg', 'BV1hv4y1V71G', 'BV1gv4y1p7Nq', 'BV1Vs4y1U7Gu', 'BV1Mo4y1H7ai']))
# re = dynamic_list.search((where('pdate') > 1680761969) & (where('pdate') < 1680848369))
# print(len(re))

# asyncio.run(download_video('BV1EM4y117CP', print))

# MEDIA_FILE_PATH = lambda name: glob.glob(os.path.join('/media', f'{legal_title(name[:10])}*'))
# ATTACHMENT_FILE_PATH = lambda name: glob.glob(os.path.join('/media/extra', f'{legal_title(name)}*'))

# print('12345678'[:5])
# g = glob.glob(os.path.join('/media', f'{legal_title(name[:30])}*'))
# print(g)

# 一首歌运动前热身拉伸《Me Too》快速激活全身🔥避免运动肌肉拉伤💦Warm up提高燃脂效率～运动前后都能跳～
# li = dynamic_list.search(where('dstatus') == -1)
# li = shazam_list.all()
# print(len(li))

# g = glob.glob('️竖屏❤️贴身秘书，油亮加倍【须须x巫小萤】*')
# print(g)
# VIDEO_DETAIL_API = lambda bvid: f'https://www.bilibili.com/video/{bvid}'
# res = requests.get(VIDEO_DETAIL_API('BV1JL411U7R9'))
# if res.status_code != 200:
#     print(f'获取 {bvid} 视频详情失败')

# # "accept_description":["超清 4K","高清 1080P+","高清 1080P","高清 720P","清晰 480P","流畅 360P"]
# quality = re.search(r'"accept_description":\["([^"]+)"', res.text)
# quality.group(1)

# dynamic_list.update({'dstatus': 0}, where('dstatus') == 100)

# try:
#     a = 1/0
# except ZeroDivisionError as err:
#     print(err, isinstance(err, Exception))
# pdate = 1680356009
# timestamp = 1680858010
# q = (where('pdate') > pdate) & (where('pdate') < timestamp) & (where('ustatus') == 0)
# dynamic_list2.update({'dstatus': -2}, q)
# mlist = dynamic_list2.search(q)
# dynamic_list.insert_multiple(mlist)
# for item in dynamic_list:
#     dynamic_list.update({'pdstr': datetime.fromtimestamp(item['pdate']).strftime("%Y-%m-%d %H:%M:%S")}, where('bvid') == item['bvid'])

# print(len(dynamic_list))

# app = Flask(__name__)

# @app.route('/', defaults={'path': ''})
# @app.route('/<path:path>')
# def catch_all(path):
#     return app.send_static_file("index.html")

# if __name__ == '__main__':
#     app.run()
# VIDEO_DETAIL_API = lambda bvid: f'https://www.bilibili.com/video/{bvid}'
# def fetch_detail(item):
#     bvid = item['bvid']
#     duration_text = item['duration_text']
#     res = requests.get(VIDEO_DETAIL_API(bvid))
#     try:
#         play_info = re.search(r'<script>window.__playinfo__=([^<]+)</script>', res.text)
#         pinfo = json.loads(play_info.group(1))
#         duration = pinfo['data']['timelength']
#     except:
#         print(f'获取 {bvid} 视频详情失败')
        
#         # 字符串反算视频时长
#         d_arr = duration_text.split(':')
#         if len(d_arr) == 2:
#             duration = (int(d_arr[0]) * 60 + int(d_arr[1])) * 1000
#         if len(d_arr) == 3:
#             duration = (int(d_arr[0]) * 3600 + int(d_arr[1]) * 60 + int(d_arr[2])) * 1000
#         return {'duration': duration}
#     else:
#         return {'duration': duration}

# for item in dynamic_list.search(where('dstatus') == 100):
#     dynamic_list.update({'dstatus': 0}, where('bvid') == item['bvid'])

# q = ((where('dstatus') == 0) | ((where('dstatus') == -1) & (where('dl_retry') < 3))) & (where('duration') > 600000)
# dy_list = dynamic_list.search(q)
# print(dy_list)

# async def async_task():
#     d = DownloaderBilibili(sess_data='71dab752%2C1696566753%2C24faa%2A41', video_concurrency=1, part_concurrency=1)
#     await d.get_video(url='https://www.bilibili.com/video/BV1ao4y1L74F', path=Path(''), image=True)
#     await d.aclose()

# asyncio.get_event_loop().run_until_complete(async_task())

# print(dynamic_list.search(where('dstatus') == 100) or 1111)