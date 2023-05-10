# -*- coding: utf-8 -*-

import sys
import re
import requests
import json
import asyncio
import logging
from datetime import datetime
from constant import *
from util import get_mp4_path, get_video_resolution, find_and_remove
from tinydb import TinyDB, Query, where
from tinydb.operations import increment
from bilix import DownloaderBilibili

# 配置logger
formatter = '%(levelname)s %(message)s'
logging.basicConfig(format=formatter, level=logging.INFO)
logger = logging.getLogger('bdm')

db = TinyDB(DB_PATH)
dynamic_list = db.table('dynamic_list')
config = db.table('config')

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

def fetch_follow(page): 
    cookie = {'SESSDATA': DYNAMIC_COOKIE}
    res = requests.get(USER_FOLLOW_API(page), cookies=cookie)
    res_json = json.loads(res.text)

    if res_json['code'] != 0:
        logger.error('获取关注列表失败，终止执行')
        sys.exit() 
    return res_json['data']

def fetch_detail(item):
    bvid = item['bvid']
    duration_text = item['duration_text']
    res = requests.get(VIDEO_DETAIL_API(bvid))
    try:
        play_info = re.search(r'<script>window.__playinfo__=([^<]+)</script>', res.text)
        pinfo = json.loads(play_info.group(1))
        # "accept_description":["超清 4K","高清 1080P+","高清 1080P","高清 720P","清晰 480P","流畅 360P"]
        max_quality = pinfo['data']['accept_description'][0]
        vwidth = pinfo['data']['dash']['video'][0]['width']
        vheight = pinfo['data']['dash']['video'][0]['height']
        is_portrait = 1 if (vwidth / vheight < 1) else 0
        duration = pinfo['data']['timelength']
    except:
        logger.info(f'获取 {bvid} 视频详情失败')
        
        # 字符串反算视频时长
        d_arr = duration_text.split(':')
        if len(d_arr) == 2:
            duration = (int(d_arr[0]) * 60 + int(d_arr[1])) * 1000
        if len(d_arr) == 3:
            duration = (int(d_arr[0]) * 3600 + int(d_arr[1]) * 60 + int(d_arr[2])) * 1000
        return {'duration': duration}
    else:
        return {'max_quality': max_quality, 'is_portrait': is_portrait, 'duration': duration}

def fetch_dynamic(page, offset): 
    cookie = {'SESSDATA': DYNAMIC_COOKIE}
    res = requests.get(USER_DYNAMIC_API(page, offset), cookies=cookie)
    res_json = json.loads(res.text)

    if res_json['code'] != 0:
        logger.error('获取动态失败，终止执行')
        sys.exit()
    
    def flat_data(item):
        uid = item['modules']['module_author']['mid']
        uname = item['modules']['module_author']['name']
        avatar = item['modules']['module_author']['face']
        pdate = item['modules']['module_author']['pub_ts']
        pdstr = datetime.fromtimestamp(pdate).strftime("%Y-%m-%d %H:%M:%S")
        title = item['modules']['module_dynamic']['major']['archive']['title']
        bvid = item['modules']['module_dynamic']['major']['archive']['bvid']
        cover = item['modules']['module_dynamic']['major']['archive']['cover']
        desc = item['modules']['module_dynamic']['major']['archive']['desc']
        duration_text = item['modules']['module_dynamic']['major']['archive']['duration_text']
        return {
            'uid': uid,
            'uname': uname,
            'title': title,
            'bvid': bvid,
            'cover': cover,
            'desc': desc,
            'duration_text': duration_text,
            'avatar': avatar, 
            'pdate': pdate, 
            'pdstr': pdstr,
            'shazam_id': 0,
            'dstatus': 0,
            'dl_retry': 0,
            'ustatus': 0,
            'up_retry': 0,
        }

    dlist = list(map(flat_data, res_json['data']['items']))
    offset = res_json['data']['offset']

    return {'dlist': dlist, 'offset': offset}

# 获取关注分组的全部用户
def update_follow():
    flist = []
    page = 1
    content_len = -1

    while (content_len != 0):
        page_list = fetch_follow(page)
        content_len = len(page_list)
        flist.extend(page_list)
        page = page + 1

    uid_list = list(map(lambda i: i['mid'], flist))
    # 存入数据库
    set_config('follow_uid', uid_list)
    logger.info(f'关注分组已更新，当前共关注 {len(uid_list)} 用户')
    return uid_list

def remove_duplicated_dynamic():
    full_list = dynamic_list.all()
    seen = set()
    dupes = []
    for item in full_list:
        bvid = item['bvid']
        doc_id = item.doc_id
        if bvid in seen:
            dupes.append(doc_id)
        else:
            seen.add(bvid)
    dynamic_list.remove(doc_ids=dupes)
    return len(dupes)

# 获取截止时间前的所有动态
def update_dynamic(cpdate, uid_list):
    flist = []
    page = 1
    offset = ''

    while (page < MAX_DYNAMIC_FETCH_PAGE):
        re = fetch_dynamic(page, offset)
        page_list = re['dlist']

        matchs = [i for (i, item) in enumerate(page_list) if item['pdate'] <= cpdate]
        if len(matchs) > 0:
            last_part = page_list[:matchs[0]]
            flist.extend(last_part)
            break

        flist.extend(page_list)
        page = page + 1
        offset = re['offset']

    filter_list = list(filter(lambda i: i['uid'] in uid_list, flist))

    add_vinfo = lambda item: {**item, **fetch_detail(item)}
    d = [add_vinfo(v) for v in filter_list]
    
    # 没有更新直接退出
    if len(d) == 0:
        logger.info(f'没有新动态')
        return

    # 存入数据库
    dynamic_list.insert_multiple(d)
    logger.info(f'新增 {len(d)} 条动态')
    # 更新截止时间
    update_date = d[0]['pdate']
    set_config('check_point', update_date)
    logger.info(f'动态截止日期更新为：{datetime.fromtimestamp(update_date).strftime("%Y-%m-%d %H:%M:%S")}')
    # 去重
    dcount = remove_duplicated_dynamic()
    if dcount > 0:
        logger.info(f'发现并移除 {dcount} 条重复动态')


# 下载任务
async def task(d, item):
    item_bvid = item['bvid']
    item_title = item['title']
    item_max_quality = item['max_quality']
    item_retry_count = item['dl_retry']
    
    # 下载中 100
    switch_dl_status(item_bvid, 100)
    try:
        await d.get_video(VIDEO_DETAIL_API(item_bvid), image=True)

        mp4_files = get_mp4_path(item_title)
        # 文件不存在
        if not mp4_files:
            return switch_dl_status(item_bvid, -2)
        # 分辨率不达标
        width, height, bitrate, fps = get_video_resolution(mp4_files[0])
        if '4K' in item_max_quality:
            if (width <= 1920) and (height <= 1920):
                return switch_dl_status(item_bvid, -3, (item_retry_count < 2) and item_title)
        if '1080P60' in item_max_quality:
            if ((width <= 1080) and (height <= 1080)) or (fps < 50):
                return switch_dl_status(item_bvid, -3, (item_retry_count < 2) and item_title)
        if '1080P+' in item_max_quality:
            if ((width <= 1080) and (height <= 1080)) or (bitrate < 2000e3):
                return switch_dl_status(item_bvid, -3, (item_retry_count < 2) and item_title)
        if '1080P' in item_max_quality:
            if (width <= 1080) and (height <= 1080):
                return switch_dl_status(item_bvid, -3, (item_retry_count < 2) and item_title)

        # 下载文件检验成功
        switch_dl_status(item_bvid, 200)
    except:
        switch_dl_status(item_bvid, -1)

def refresh_title(item):
    bvid = item['bvid']
    cookie = {'SESSDATA': DYNAMIC_COOKIE}
    res = requests.get(VIDEO_VIEW_API(bvid), cookies=cookie)
    res_json = json.loads(res.text)
    if res_json['code'] == 0:
        new_title = res_json['data']['title']
        dynamic_list.update({'title': new_title}, where('bvid') == bvid)
        return {**item, 'title': new_title}
    return item
     
# 下载视频列表
async def download_video_list(origin_list):
    d = DownloaderBilibili(videos_dir=MEDIA_ROOT, sess_data=DOWNLOAD_COOKIE, video_concurrency=1, part_concurrency=1)
    
    for item in list(map(refresh_title, origin_list)):
        await task(d, item)

    await d.aclose()

# async task
async def async_task():
    sort_by_date = lambda li: sorted(li, key=lambda i: i['pdate'], reverse=False)
    # 时长小于10分钟
    q_limit = where('duration') < 600000
    # 下载中
    q1 = (where('dstatus') == 100) & q_limit
    # 未下载
    q2 = (where('dstatus') == 0) & q_limit
    # 下载失败 && 可重试
    q3 = ((where('dstatus') < 0) & (where('dl_retry') < 3)) & q_limit
    ing_list = sort_by_date(dynamic_list.search(q1))
    wait_list = sort_by_date(dynamic_list.search(q2))
    retry_list = sort_by_date(dynamic_list.search(q3))
    merge_list = [*ing_list, *wait_list, *retry_list]
    
    await download_video_list(merge_list[:CONCURRENT_TASK_NUM])

if __name__ == '__main__':
    logger.info('定时任务：开始获取最新动态')
    update_dynamic(get_config('check_point'), update_follow())
    asyncio.get_event_loop().run_until_complete(async_task())
    db.close()
