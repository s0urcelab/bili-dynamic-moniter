# -*- coding: utf-8 -*-

import os
import glob
import html
import re
import json
import subprocess
from constant import *
from tinydb import TinyDB, Query, where
from tinydb.operations import increment

db = TinyDB(DB_PATH)
config = db.table('config')
dynamic_list = db.table('dynamic_list', cache_size=0)

def replace_illegal(s: str):
    s = s.strip()
    s = html.unescape(s)  # handel & "...
    s = re.sub(r"[/\\:*?\"<>|\n]", '', s)  # replace illegal filename character
    return s
def legal_title(*parts: str, join_str: str = '-'):
    return join_str.join(filter(lambda x: len(x) > 0, map(replace_illegal, parts)))

def get_mp4_path(name):
    return glob.glob(os.path.join(MEDIA_ROOT, f'{glob.escape(legal_title(name[:30]))}*.mp4'))

def get_frag_path(name):
    return glob.glob(os.path.join(MEDIA_ROOT, f'{glob.escape(legal_title(name[:30]))}*'))

def get_cover_path(name): 
    return glob.glob(os.path.join(MEDIA_ROOT, 'extra', f'{glob.escape(legal_title(name[:30]))}*'))

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

# 查找本地文件并删除
def find_and_remove(name):
    for item in get_frag_path(name):
        os.remove(item)
    for item in get_cover_path(name):
        os.remove(item)

    