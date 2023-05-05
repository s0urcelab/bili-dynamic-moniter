# -*- coding: utf-8 -*-

import os
import asyncio
import glob
import html
import re
import json
import subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from tinydb import TinyDB, Query, where
from tinydb.operations import increment
from bilix import DownloaderBilibili
from shazamio import Shazam, Serialize

# 加载.env的环境变量
load_dotenv()

DOWNLOAD_COOKIE = os.environ['DL_COOKIE']
DB_PATH = os.environ['DB_PATH']

MP4_FILE_PATH = lambda name: glob.glob(os.path.join('/media', f'{glob.escape(legal_title(name[:30]))}*.mp4'))
MEDIA_FILE_PATH = lambda name: glob.glob(os.path.join('/media', f'{glob.escape(legal_title(name[:30]))}*'))
ATTACHMENT_FILE_PATH = lambda name: glob.glob(os.path.join('/media/extra', f'{glob.escape(legal_title(name[:30]))}*'))

db = TinyDB(DB_PATH)
config = db.table('config')
shazam_list = db.table('shazam_list', cache_size=0)
dynamic_list = db.table('dynamic_list', cache_size=0)

def get_video_resolution(filename):
    cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,bit_rate,r_frame_rate', '-of', 'json']
    cmd.append(filename)
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    result_dict = json.loads(result.stdout)
    width = result_dict['streams'][0]['width']
    height = result_dict['streams'][0]['height']
    bitrate = int(result_dict['streams'][0]['bit_rate'])
    frame_rate = result_dict['streams'][0]['r_frame_rate']
    numerator, denominator = map(int, frame_rate.split('/'))
    fps = numerator / denominator
    return (width, height, bitrate, fps)

def replace_illegal(s: str):
    s = s.strip()
    s = html.unescape(s)  # handel & "...
    s = re.sub(r"[/\\:*?\"<>|\n]", '', s)  # replace illegal filename character
    return s
def legal_title(*parts: str, join_str: str = '-'):
    return join_str.join(filter(lambda x: len(x) > 0, map(replace_illegal, parts)))
    
def get_config(key):
    is_exist = where(key).exists()
    t = config.get(is_exist)
    if t != None:
        return t[key]
    else:
        return t

def set_config(key, value):
    config.upsert({key: value}, where(key).exists())

# 切换投稿下载状态
def switch_dl_status(bvid, status, title=None):
    dynamic_list.update({'dstatus': status}, where('bvid') == bvid)
    if status < 0:
        dynamic_list.update(increment('dl_retry'), where('bvid') == bvid)
        if title:
            find_and_remove(title)

# 下载任务
async def task(d, bvid):
    # 下载中 100
    switch_dl_status(bvid, 100)
    await d.get_video(f'https://www.bilibili.com/video/{bvid}', image=True)
    
     
# 下载视频列表
async def download_video_list(li, err_cb):
    d = DownloaderBilibili(videos_dir='/media', sess_data=DOWNLOAD_COOKIE, video_concurrency=1, part_concurrency=1)
    coros = [task(d, i['bvid']) for i in li]
    ret_list = await asyncio.gather(*coros, return_exceptions=True)
    for idx, item in enumerate(ret_list):
        item_bvid = li[idx]['bvid']
        item_title = li[idx]['title']
        item_max_quality = li[idx]['max_quality']
        item_retry_count = li[idx]['dl_retry']
        if isinstance(item, Exception):
            switch_dl_status(item_bvid, -1)
        else:
            mp4_files = MP4_FILE_PATH(item_title)
            # 文件不存在
            if len(mp4_files) == 0:
                return switch_dl_status(item_bvid, -2)
            # 分辨率不达标
            width, height, bitrate, fps = get_video_resolution(mp4_files[0])
            if '4K' in item_max_quality:
                if (width <= 1920) and (height <= 1920):
                    return switch_dl_status(item_bvid, -3, (item_retry_count < 3) and item_title)
            if '1080P60' in item_max_quality:
                if ((width <= 1080) and (height <= 1080)) or (fps < 50):
                    return switch_dl_status(item_bvid, -3, (item_retry_count < 3) and item_title)
            if '1080P+' in item_max_quality:
                if ((width <= 1080) and (height <= 1080)) or (bitrate < 2000e3):
                    return switch_dl_status(item_bvid, -3, (item_retry_count < 3) and item_title)
            if '1080P' in item_max_quality:
                if (width <= 1080) and (height <= 1080):
                    return switch_dl_status(item_bvid, -3, (item_retry_count < 3) and item_title)

            # 下载文件检验成功
            return switch_dl_status(item_bvid, 200)
    await d.aclose()

async def match_bgm(li, err_cb):
    shazam = Shazam()
    # coros = [shazam.recognize_song(MEDIA_FILE_PATH(i["title"])[0]) for i in li]
    coros = []
    for i in li:
        origin_title = i["title"]
        local_path_group = MEDIA_FILE_PATH(origin_title)
        if len(local_path_group) == 0:
            # 本地文件不存在
            dynamic_list.update({'shazam_id': -2}, where('bvid') == i['bvid'])
            err_cb(f'无法识别该视频：{i["bvid"]}，本地文件可能不存在')
        else:
            possible_song = shazam.recognize_song(local_path_group[0])
            coros.append(possible_song)
            # try:
            # except:
            #     err_cb(f'Shazam访问出错')
            #     # raise
            # else:
            #     coros.append(possible_song)
    ret_list = await asyncio.gather(*coros, return_exceptions=True)
    # res_list = list(filter(lambda v: not isinstance(v, Exception), ret_list))
    # serialized_list = list(map(Serialize.full_track, res_list))
    for idx, item in enumerate(ret_list):
        if not isinstance(item, Exception):
            item_bvid = li[idx]['bvid']
            sez = Serialize.full_track(item)
            if len(sez.matches) == 0:
                # 未找到匹配的bgm
                dynamic_list.update({'shazam_id': -1}, where('bvid') == item_bvid)
            else:
                shazam_id = sez.matches[0].id
                shazam_title = sez.track.title
                dynamic_list.update({'shazam_id': shazam_id}, where('bvid') == item_bvid)
                if not shazam_list.contains(where('id') == shazam_id):
                    shazam_list.insert({'id': shazam_id, 'title': shazam_title})

# 查找本地文件并删除
def find_and_remove(name):
    for item in MEDIA_FILE_PATH(name):
        os.remove(item)
    for item in ATTACHMENT_FILE_PATH(name):
        os.remove(item)

    