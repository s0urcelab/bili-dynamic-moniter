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
from util import set_config, get_config, download_video_list
from tinydb import TinyDB, Query, where

# 加载.env的环境变量
load_dotenv()
# 配置logger
logger = logging.getLogger()

DB_PATH = os.environ['DB_PATH']
USER_DYNAMIC_API = lambda page,offset: f'https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all?timezone_offset=-480&type=video&page={page}&features=itemOpusStyle&offset={offset}'
USER_FOLLOW_API = lambda page: f'https://api.bilibili.com/x/relation/tag?mid=543741&tagid=37444368&pn={page}&ps=20'
VIDEO_DETAIL_API = lambda bvid: f'https://www.bilibili.com/video/{bvid}'

DYNAMIC_COOKIE = os.environ['FO_COOKIE']
MAX_DYNAMIC_FETCH_PAGE = int(os.environ['MAX_DYNAMIC_FETCH_PAGE'])
CONCURRENT_TASK_NUM = int(os.environ['CONCURRENT_TASK_NUM'])

db = TinyDB(DB_PATH)
config = db.table('config')
dynamic_list = db.table('dynamic_list')

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

# async task
async def async_task():
    # 未下载 || 可重试 && 时长小于10分钟
    q_limit = where('duration') < 600000
    q1 = (where('dstatus') == 0) & q_limit
    q2 = ((where('dstatus') == -1) & (where('dl_retry') < 3)) & q_limit
    wait_list = dynamic_list.search(q1)
    retry_list = dynamic_list.search(q2)

    dl_list = sorted(wait_list if len(wait_list) > 0 else retry_list, key=lambda i: i['pdate'], reverse=True)[:CONCURRENT_TASK_NUM]
    await download_video_list(dl_list, logger.warning)

if __name__ == '__main__':
    logger.info('定时任务：开始获取最新动态')
    update_dynamic(get_config('check_point'), update_follow())
    asyncio.get_event_loop().run_until_complete(async_task())
