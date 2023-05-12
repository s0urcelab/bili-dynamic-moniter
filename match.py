# -*- coding: utf-8 -*-

import logging
from constant import *
from util import get_mp4_path
from tinydb import TinyDB, Query, where
from shazamio import Shazam, Serialize

# 配置logger
# formatter = '%(asctime)s %(levelname)s %(message)s'
# logging.basicConfig(format=formatter, datefmt='%Y-%m-%d %H:%M:%S', level=logging.INFO)
logger = logging.getLogger('bdm')
    
async def match():
    shazam = Shazam()
    
    # 连接数据库
    with TinyDB(DB_PATH) as db:
        dynamic_list = db.table('dynamic_list')
        shazam_list = db.table('shazam_list')
    
        async def shazam_bgm(match_list):
            for item in match_list:
                bvid = item['bvid']
                origin_title = item['title']
                
                local_path = get_mp4_path(item)
                if not local_path:
                    # 本地文件不存在
                    dynamic_list.update({'shazam_id': -2}, where('bvid') == bvid)
                    logger.error(f'无法识别该视频：{origin_title}，本地文件可能不存在')
                    continue
                    
                try:
                    possible_song = await shazam.recognize_song(local_path[0])
                    sez = Serialize.full_track(possible_song)
                    if len(sez.matches) == 0:
                        # 未找到匹配的bgm
                        dynamic_list.update({'shazam_id': -1}, where('bvid') == bvid)
                        continue
                    
                    # 匹配成功
                    shazam_id = sez.matches[0].id
                    shazam_title = sez.track.title
                    dynamic_list.update({'shazam_id': shazam_id}, where('bvid') == bvid)
                    if not shazam_list.contains(where('id') == shazam_id):
                        shazam_list.insert({'id': shazam_id, 'title': shazam_title})
                except:
                    dynamic_list.update({'shazam_id': -3}, where('bvid') == bvid)
                    logger.error(f'shazam错误：{origin_title}')
    
        logger.info('定时任务：匹配BGM')   
        q_sz = (where('shazam_id') == 0) & (where('dstatus') == 200)
        wait_match_list = sorted(dynamic_list.search(q_sz), key=lambda i: i['pdate'], reverse=False)
        await shazam_bgm(wait_match_list[:CONCURRENT_TASK_NUM])

