# -*- coding: utf-8 -*-
import os
import logging
from constant import *
from util import get_mp4_path, get_video_resolution, find_and_remove, legal_title
from tinydb import TinyDB, Query, where
from tinydb.operations import increment
from yt_dlp import YoutubeDL

logger = logging.getLogger('bdm')

class DownloadError(Exception):
    def __init__(self, message, code=-1):
        self.message = message
        self.code = code

    def __str__(self):
        return self.message

def download():
    # 连接数据库
    with TinyDB(DB_PATH) as db:
        dynamic_list = db.table('dynamic_list')

    # 切换投稿下载状态
    def switch_dl_status(bvid, status, item=None):
        dynamic_list.update({'dstatus': status}, where('bvid') == bvid)
        if status < 0:
            dynamic_list.update(increment('dl_retry'), where('bvid') == bvid)
            if item:
                find_and_remove(item)

    # 下载
    def download_video(item):
        item_bvid = item['bvid']
        item_title = item['title']
        item_max_quality = item['max_quality']
        item_retry_count = item['dl_retry']
        class MyLogger:
            def debug(self, msg):
                pass
            def warning(self, msg):
                pass
            def error(self, msg):
                logger.error(msg)

        ydl_opts = {
            'outtmpl': os.path.join(MEDIA_ROOT, f'{legal_title(item_title)}-{item_bvid}.%(ext)s'),
            'writethumbnail': True,
            'cookiefile': DL_COOKIE_FILE,
            'logger': MyLogger(),
        }
        
        # 开始下载
        logger.info(f'开始下载：{item_title}')
        switch_dl_status(item_bvid, 100)
        try:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([VIDEO_DETAIL_API(item_bvid)])

            mp4_files = get_mp4_path(item)
            # 文件不存在
            if not mp4_files:
                raise DownloadError('视频文件不存在', -2)
            # 分辨率不达标
            width, height, bitrate, fps = get_video_resolution(mp4_files[0])
            if '4K' in item_max_quality:
                if (width <= 1920) and (height <= 1920):
                    raise DownloadError('分辨率不达标', -3)
            if '1080P60' in item_max_quality:
                if ((width <= 1080) and (height <= 1080)) or (fps < 50):
                    raise DownloadError('分辨率不达标', -3)
            if '1080P+' in item_max_quality:
                if ((width <= 1080) and (height <= 1080)) or (bitrate < 2000e3):
                    raise DownloadError('分辨率不达标', -3)
            if '1080P' in item_max_quality:
                if (width <= 1080) and (height <= 1080):
                    raise DownloadError('分辨率不达标', -3)

            # 下载文件检验成功
            switch_dl_status(item_bvid, 200)
            logger.info(f'下载成功：{item_title}')
        except Exception as err:
            if err.code == -3:
                switch_dl_status(item_bvid, err.code, (item_retry_count < 2) and item)
            else:
                switch_dl_status(item_bvid, err.code)
            logger.error(f'下载失败[{err.code}]： {item_title}')

    # def refresh_title(item):
    #     bvid = item['bvid']
    #     cookie = {'SESSDATA': DYNAMIC_COOKIE}
    #     res = requests.get(VIDEO_VIEW_API(bvid), cookies=cookie)
    #     res_json = json.loads(res.text)
    #     if res_json['code'] == 0:
    #         new_title = res_json['data']['title']
    #         dynamic_list.update({'title': new_title}, where('bvid') == bvid)
    #         return {**item, 'title': new_title}
    #     return item
        
    
    logger.info('定时任务：下载视频')
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
    
    for item in merge_list[:CONCURRENT_TASK_NUM]:
        download_video(item)
