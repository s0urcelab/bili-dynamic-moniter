# -*- coding: utf-8 -*-

import logging
from constant import *
from util import get_mp4_path, find_and_remove
from shazamio import Shazam, Serialize

logger = logging.getLogger('bdm')
    
async def shazam_match(client):
    shazam = Shazam()
    dynamic_list = client.dance.dynamic_list
    shazam_list = client.dance.shazam_list

    async def shazam_bgm(match_list):
        for item in match_list:
            vid = item['vid']
            origin_title = item['title']
            
            local_path = get_mp4_path(item)
            if not local_path:
                # 本地文件不存在
                dynamic_list.update_one({"vid": vid}, {"$set": {"shazam_id": -2}})
                logger.error(f'无法识别该视频：{origin_title}，本地文件可能不存在')
                continue
                
            try:
                possible_song = await shazam.recognize_song(local_path[0])
                sez = Serialize.full_track(possible_song)
                if len(sez.matches) == 0:
                    # 未找到匹配的bgm
                    dynamic_list.update_one({"vid": vid}, {"$set": {"shazam_id": -1}})
                    continue
                
                # 匹配成功
                shazam_id = sez.matches[0].id
                shazam_title = sez.track.title
                dynamic_list.update_one({"vid": vid}, {"$set": {"shazam_id": shazam_id}})
                
                try:
                    shazam_list.insert_one({'id': shazam_id, 'title': shazam_title})
                except:
                    pass
            except:
                dynamic_list.update_one({"vid": vid}, {"$set": {"shazam_id": -3}})
                logger.error(f'shazam错误：{origin_title}')
            finally:
                # 匹配后删除已上传天翼云的资源
                if item['fid']:
                    find_and_remove(item)

    logger.info('定时任务：匹配BGM')
    q_sz = {"$and": [{"shazam_id": 0}, {"dstatus": 200}]}
    wait_match_list = dynamic_list.find(q_sz, {"_id": 0}).sort([("pdate", -1)]).limit(CONCURRENT_TASK_NUM)
    await shazam_bgm(wait_match_list)
