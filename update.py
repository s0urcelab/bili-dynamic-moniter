# -*- coding: utf-8 -*-
import re
import requests
import json
import logging
from datetime import datetime
from constant import *

logger = logging.getLogger('bdm')

def update(client):
    dynamic_list = client.dance.dynamic_list
    config = client.dance.config
    follow_list = client.dance.follow_list

    def fetch_follow(page): 
        cookie = {'SESSDATA': DYNAMIC_COOKIE}
        res = requests.get(USER_FOLLOW_API(page), cookies=cookie)
        res_json = json.loads(res.text)

        if res_json['code'] != 0:
            # logger.error()
            raise Exception('获取关注列表失败，终止执行')
        return res_json['data']

    def fetch_detail(item):
        bvid = item['vid']
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
            logger.error(f'获取 {bvid} 视频详情失败')
            # 直接失败处理
            return {'dstatus': -9}
            
            # # 字符串反算视频时长
            # d_arr = duration_text.split(':')
            # if len(d_arr) == 2:
            #     duration = (int(d_arr[0]) * 60 + int(d_arr[1])) * 1000
            # if len(d_arr) == 3:
            #     duration = (int(d_arr[0]) * 3600 + int(d_arr[1]) * 60 + int(d_arr[2])) * 1000
            # return {'duration': duration}
        else:
            return {'max_quality': max_quality, 'is_portrait': is_portrait, 'duration': duration}

    def fetch_dynamic(page, offset): 
        cookie = {'SESSDATA': DYNAMIC_COOKIE}
        res = requests.get(USER_DYNAMIC_API(page, offset), cookies=cookie)
        res_json = json.loads(res.text)

        if res_json['code'] != 0:
            raise Exception('获取动态失败，终止执行')
        
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
                'source': 2,
                'uid': uid,
                'uname': uname,
                'title': title,
                'vid': bvid,
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
    def refresh_follow():
        flist = []
        page = 1
        content_len = -1

        while (content_len != 0):
            page_list = fetch_follow(page)
            content_len = len(page_list)
            flist.extend(page_list)
            page = page + 1

        uid_set = set(map(lambda i:  i['mid'], flist))
        user_list = list(map(lambda i: {"uid": i['mid'], "uname": i['uname']}, flist))
        # 存入数据库
        try:
            follow_list.insert_many(user_list, ordered=False)
        except:
            logger.info(f'忽略重复的关注用户')
        all_users = follow_list.find({}, {"_id": 0})
        for user in all_users:
            if user['uid'] not in uid_set:
                follow_list.delete_one({"uid": user['uid']})
        total_user = follow_list.count_documents({})
        logger.info(f'关注分组已更新，当前共关注 {total_user} 用户')
        return uid_set

    # def remove_duplicated_dynamic():
    #     full_list = dynamic_list.find()
    #     seen = set()
    #     dupes = []
    #     for item in full_list:
    #         vid = item['vid']
    #         doc_id = item.doc_id
    #         if vid in seen:
    #             dupes.append(doc_id)
    #         else:
    #             seen.add(vid)
    #     dynamic_list.remove(doc_ids=dupes)
    #     return len(dupes)

    """
    获取截止时间 check_point 前的所有关注用户 uid_set 的动态
    """
    logger.info('定时任务：获取最新动态')
    cpdate = config.find_one({"check_point": {"$exists": True}})['check_point']
    uid_set = refresh_follow()
    flist = []
    page = 1
    offset = ''

    while (page < MAX_DYNAMIC_FETCH_PAGE):
        single_part = fetch_dynamic(page, offset)
        page_list = single_part['dlist']

        matchs = [i for (i, item) in enumerate(page_list) if item['pdate'] <= cpdate]
        if len(matchs) > 0:
            last_part = page_list[:matchs[0]]
            flist.extend(last_part)
            break

        flist.extend(page_list)
        page = page + 1
        offset = single_part['offset']

    filter_list = list(filter(lambda i: i['uid'] in uid_set, flist))

    add_vinfo = lambda item: {**item, **fetch_detail(item)}
    d = [add_vinfo(v) for v in filter_list]
    
    # 没有更新直接退出
    if len(d) == 0:
        logger.info(f'没有新动态')
        return

    # 存入数据库
    try:
        dynamic_list.insert_many(d, ordered=False)
    except:
        logger.info(f'忽略重复vid')
    
    logger.info(f'新增 {len(d)} 条动态')
    # 更新截止时间
    update_date = d[0]['pdate']
    config.update_one({"check_point": {"$exists": True}}, {"$set": {"check_point": update_date}}, upsert=True)
    logger.info(f'动态截止日期更新为：{datetime.fromtimestamp(update_date).strftime("%Y-%m-%d %H:%M:%S")}')
    # 去重
    # dcount = remove_duplicated_dynamic()
    # if dcount > 0:
    #     logger.info(f'发现并移除 {dcount} 条重复动态')
