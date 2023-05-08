# -*- coding: utf-8 -*-

import asyncio
import logging
from constant import *
from util import get_mp4_path
from tinydb import TinyDB, Query, where
from shazamio import Shazam, Serialize

# 配置logger
formatter = '%(levelname)s %(message)s'
logging.basicConfig(format=formatter, level=logging.INFO)
logger = logging.getLogger('bdm')

db = TinyDB(DB_PATH)
dynamic_list = db.table('dynamic_list', cache_size=0)
shazam_list = db.table('shazam_list', cache_size=0)

async def match_bgm(li, err_cb):
    shazam = Shazam()
    coros = []
    for i in li:
        origin_title = i["title"]
        local_path_group = get_mp4_path(origin_title)
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
                dynamic_list.update({'shazam_id': -1},
                                    where('bvid') == item_bvid)
            else:
                shazam_id = sez.matches[0].id
                shazam_title = sez.track.title
                dynamic_list.update({'shazam_id': shazam_id},
                                    where('bvid') == item_bvid)
                if not shazam_list.contains(where('id') == shazam_id):
                    shazam_list.insert(
                        {'id': shazam_id, 'title': shazam_title})


async def async_task():
    q_sz = (where('shazam_id') == 0) & (where('dstatus') == 200)
    wait_match_list = sorted(dynamic_list.search(
        q_sz), key=lambda i: i['pdate'], reverse=True)[:CONCURRENT_TASK_NUM]
    await match_bgm(wait_match_list, logger.warning)

if __name__ == '__main__':
    logger.info('定时任务：开始匹配bgm')
    asyncio.get_event_loop().run_until_complete(async_task())
