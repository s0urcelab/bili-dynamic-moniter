# -*- coding: utf-8 -*-

import os
import glob
import html
import re
import json
import subprocess
from constant import *

def replace_illegal(s: str):
    s = s.strip()
    s = html.unescape(s)  # handel & "...
    s = re.sub(r"[/\\:*?\"<>|\n]", '', s)  # replace illegal filename character
    return s
def legal_title(*parts: str, join_str: str = '-'):
    return join_str.join(filter(lambda x: len(x) > 0, map(replace_illegal, parts)))

"""
from_local  => source: hash 本地手动下载，标题-bvid-hash.mp4
none        => source: 0 bilix下载，标题.mp4
from_import => source: 1 外部bvid导入，标题-vid.mp4
none        => source: 2 从动态下载，标题-vid.mp4
none        => source: 3 外部acid导入，标题-vid.mp4
"""
def get_mp4_path(item):
    vid = item['vid']
    source = item['source']
    title = glob.escape(legal_title(item['title'][:30]))
    
    if source in [0]:
        return glob.glob(os.path.join(MEDIA_ROOT, f'{title}*.mp4'))
    elif source in [1, 2, 3]:
        return glob.glob(os.path.join(MEDIA_ROOT, f'*-{glob.escape(vid)}.mp4'))
    else:
        return glob.glob(os.path.join(MEDIA_ROOT, f'*{source}*.mp4'))

def get_cover_path(item):
    vid = item['vid']
    source = item['source']
    title = glob.escape(legal_title(item['title'][:30]))
    
    if source in [0]:
        return glob.glob(os.path.join(MEDIA_ROOT, f'{title}*.jpg'))
    elif source in [1, 2, 3]:
        result = []
        for ext in ('.jpg', '.png', '.jpeg', '.gif'):
            files = glob.glob(os.path.join(MEDIA_ROOT, f'*-{glob.escape(vid)}{ext}'))
            result.extend(files)
        return result
    else:
        return glob.glob(os.path.join(MEDIA_ROOT, f'*{source}*.png'))

def get_frag_path(item):
    vid = item['vid']
    
    return glob.glob(os.path.join(MEDIA_ROOT, f'*-{glob.escape(vid)}.f[0-9]*'))

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

# 查找本地文件并删除
def find_and_remove(item):
    for i in get_frag_path(item):
        os.remove(i)
    for i in get_mp4_path(item):
        os.remove(i)
    for i in get_cover_path(item):
        os.remove(i)

def get_dl_url(item):
    vid = item['pure_vid'] if ('pure_vid' in item) else item['vid']
    item_p = item['p'] if ('p' in item) else 1
    item_src = item['source']
    API = ACFUN_VIDEO_PLAY_API if (item_src == 3) else VIDEO_DETAIL_API
    return API(vid, item_p)