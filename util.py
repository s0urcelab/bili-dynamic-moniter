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
from_import => source: 1 外部bvid导入，标题.mp4
none        => source: 0 bilix下载，标题.mp4
none        => source: 2 从动态下载，标题-bvid.mp4
none        => source: 3 外部acid导入，标题-acid.mp4
"""
def get_mp4_path(item):
    source = item['source']
    title = glob.escape(legal_title(item['title'][:30]))
    if source in [0, 1]:
        return glob.glob(os.path.join(MEDIA_ROOT, f'{title}*.mp4'))
    else:
        key = item['bvid'] if (source == 2) else item['source']
        return glob.glob(os.path.join(MEDIA_ROOT, f'*{key}*.mp4'))

def get_cover_path(item):
    source = item['source']
    title = glob.escape(legal_title(item['title'][:30]))
    if source in [0, 1]:
        return glob.glob(os.path.join(MEDIA_ROOT, f'{title}*.jpg'))
    else:
        key = item['bvid'] if (source == 2) else item['source']
        result = []
        for ext in ('.jpg', '.png'):
            files = glob.glob(os.path.join(MEDIA_ROOT, f'*{key}*{ext}'))
            result.extend(files)
        return result

def get_frag_path(bvid):
    return glob.glob(os.path.join(MEDIA_ROOT, f'*-{bvid}*'))

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
    for i in get_frag_path(item['bvid']):
        os.remove(i)
    for i in get_mp4_path(item):
        os.remove(i)
    for i in get_cover_path(item):
        os.remove(i)

    