# -*- coding: utf-8 -*-
import os
import logging
from constant import *
from util import get_mp4_path, get_video_resolution, find_and_remove, legal_title, get_dl_url, get_cover_path
from yt_dlp import YoutubeDL
from cloud189.client import Cloud189Client

logger = logging.getLogger('bdm')

class DownloadError(Exception):
    def __init__(self, message, code):
        self.message = message
        self.code = code

    def __str__(self):
        return self.message

def download(client):
    dynamic_list = client.dance.dynamic_list
    # client189 = Cloud189Client(username=CLOUD189_USERNAME, password=CLOUD189_PASSWORD)
    client189 = Cloud189Client(cookies=CLOUD189_COOKIES)

    # 切换投稿下载状态
    def switch_dl_status(vid, status, item=None, add=None):
        set_field = {"dstatus": status, **add} if add else {"dstatus": status}
        dynamic_list.update_one({"vid": vid}, {"$set": set_field})
        if status < 0:
            dynamic_list.update_one({"vid": vid}, {'$inc': {'dl_retry': 1}})
        if status < 0 and item:
            find_and_remove(item)

    # 下载
    def download_video(item):
        item_vid = item['vid']
        item_title = item['title']
        item_max_quality = item['max_quality']
        item_retry_count = item['dl_retry']
        class YTBLogger:
            def debug(self, msg):
                pass
            def warning(self, msg):
                pass
            def error(self, msg):
                logger.error(msg)

        ydl_opts = {
            'outtmpl': os.path.join(MEDIA_ROOT, f'{legal_title(item_title)}-{item_vid}.%(ext)s'),
            'writethumbnail': True,
            'cookiefile': DL_COOKIE_FILE,
            'format_sort': ['size'],
            'updatetime': False,
            'logger': YTBLogger(),
        }

        # 开始下载
        logger.info(f'开始下载[云盘]：{item_title} {item_vid}')
        switch_dl_status(item_vid, 100)
        try:
            with YoutubeDL(ydl_opts) as ydl:
                url = get_dl_url(item)
                ydl.download([url])

            mp4_files = get_mp4_path(item)
            # cover_files = get_cover_path(item)
            # 上传视频to天翼云盘
            fid = client189.upload(mp4_files[0], CLOUD189_TARGET_FOLDER_ID, item_vid)
            # 上传封面to天翼云盘
            # cover_fid = client189.upload(cover_files[0], CLOUD189_TARGET_FOLDER_ID, item_vid)
            
            # 文件不存在
            if not mp4_files:
                raise DownloadError('视频文件不存在', -2)
            # 分辨率不达标
            width, height, bitrate, fps = get_video_resolution(mp4_files[0])
            if ('4K' in item_max_quality) or ('2160P' in item_max_quality):
                if (width <= 1920) and (height <= 1920):
                    raise DownloadError('分辨率不达标', -3)
            # if '1080P60' in item_max_quality:
            #     if ((width <= 1080) and (height <= 1080)) or (fps < 50):
            #         raise DownloadError('分辨率不达标', -3)
            # if '1080P+' in item_max_quality:
            #     if ((width <= 1080) and (height <= 1080)) or (bitrate < 2000e3):
            #         raise DownloadError('分辨率不达标', -3)
            if '1080P' in item_max_quality:
                if (width <= 1080) and (height <= 1080):
                    raise DownloadError('分辨率不达标', -3)

            # 下载文件检验成功
            switch_dl_status(item_vid, DSTATUS.LOCAL, item, {"fid": fid})
            logger.info(f'下载成功[云盘]：{item_title} {item_vid}')
        except DownloadError as err:
            if err.code == -3:
                switch_dl_status(item_vid, err.code, (item_retry_count < 2) and item)
            else:
                switch_dl_status(item_vid, err.code)
            logger.error(f'下载失败[{err}]： {item_title}')
        except Exception as err:
            switch_dl_status(item_vid, -1, item)
            logger.error(f'下载失败[YoutubeDL]： {item_title}')
            logger.error(err, exc_info=True)

    logger.info('定时任务：下载视频')
    # 时长小于10分钟且大于20秒
    # 精选
    qs = {"$and": [{"ustatus": {"$gte": USTATUS.SELECTED}}, {"dstatus": DSTATUS.DEFAULT}]}
    # 下载中
    q1 = {"$and": [{"duration": {"$lt": 600}}, {"duration": {"$gt": 20}}, {"dstatus": DSTATUS.DOWNLOADING}]}
    # 未下载
    q2 = {"$and": [{"duration": {"$lt": 600}}, {"duration": {"$gt": 20}}, {"dstatus": DSTATUS.DEFAULT}]}
    # 下载失败 && 可重试
    q3 = {"$and": [{"duration": {"$lt": 600}}, {"duration": {"$gt": 20}}, {"dstatus": {"$lt": DSTATUS.DEFAULT}}, {"dstatus": {"$ne": -11}}, {"dstatus": {"$ne": -9}}, {"dl_retry": {"$lt": 3}}]}

    sel_list = dynamic_list.find(qs, {"_id": 0}).sort([("pdate", -1)])
    ing_list = dynamic_list.find(q1, {"_id": 0}).sort([("pdate", -1)])
    wait_list = dynamic_list.find(q2, {"_id": 0}).sort([("pdate", -1)])
    retry_list = dynamic_list.find(q3, {"_id": 0}).sort([("pdate", -1)])
    merge_list = [*sel_list, *ing_list, *wait_list, *retry_list]

    for item in merge_list[:CONCURRENT_TASK_NUM]:
        download_video(item)
