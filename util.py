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

def get_mp4_path(name):
    return glob.glob(os.path.join(MEDIA_ROOT, f'{glob.escape(legal_title(name[:30]))}*.mp4'))

def get_frag_path(name):
    return glob.glob(os.path.join(MEDIA_ROOT, f'{glob.escape(legal_title(name[:30]))}*'))

def get_cover_path(name): 
    return glob.glob(os.path.join(MEDIA_ROOT, 'extra', f'{glob.escape(legal_title(name[:30]))}*'))

def get_local_mp4(hash):
    return glob.glob(os.path.join(MEDIA_ROOT, 'manual', f'*{hash}*.mp4'))

def get_local_cover(hash):
    return glob.glob(os.path.join(MEDIA_ROOT, 'manual', f'*{hash}*.png'))

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
def find_and_remove(name):
    for item in get_frag_path(name):
        os.remove(item)
    for item in get_cover_path(name):
        os.remove(item)

    