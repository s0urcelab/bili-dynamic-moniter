# -*- coding: utf-8 -*-

import io
import os
import requests
import json
import asyncio
from datetime import datetime
from util import get_config, set_config, switch_dl_status, find_and_remove
from tinydb import TinyDB, Query, where
from flask import Flask, flash, request

DEBUG = os.environ.get('DEBUG')
DB_PATH = os.environ['DB_PATH']

app = Flask(__name__)

db = TinyDB(DB_PATH)
config = db.table('config')
shazam_list = db.table('shazam_list', cache_size=0)
dynamic_list = db.table('dynamic_list', cache_size=0)

# 托管静态资源
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    return app.send_static_file("index.html")

# 设定截止时间
@app.route('/api/init/<datestring>')
def init_cpdate(datestring):
    cpdate = int(datetime.strptime(datestring, "%Y-%m-%d %H:%M:%S").timestamp())
    set_config('check_point', cpdate)
    return {'code': 0, 'data': f'动态截止日期初始化为：{datestring}'}

# 动态列表
@app.route('/api/list')
def dynamic_list_api():
    page = int(request.args.get('page') or 1)
    size = int(request.args.get('size') or 50)
    # 0全部，1下载失败
    dtype = int(request.args.get('dtype') or 0)
    q = where('dstatus') == -1 if dtype == 1 else where('bvid').exists()
    all_list = sorted(dynamic_list.search(q), key=lambda i: i['pdate'], reverse=True)
    total = len(all_list)
    st = (page - 1) * size
    ed = page * size
    current_list = all_list[st:ed]
    def add_shazam(item):
        q = where('id') == item['shazam_id']
        target = shazam_list.get(q)
        if target != None:
            return {**item, 'etitle': target['title']}
        else:
            return item
    return {'code': 0, 'data': list(map(add_shazam, current_list)), 'total': total }

# 占用空间情况
@app.route('/api/folder.size')
def folder_size():
    def get_dir_size(path='/media'):
        total = 0
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_file():
                    total += entry.stat().st_size
                elif entry.is_dir():
                    total += get_dir_size(entry.path)
        return round(total / (1024 ** 3), 2)
    
    return {'code': 0, 'data': f'{get_dir_size()}GB'}

# 重试下载视频
@app.route('/api/retry/<bvids>')
def retry_dl_video(bvids):
    for bvid in bvids.split(','):
        target = dynamic_list.get(where('bvid') == bvid)
        if target != None:
            find_and_remove(target['title'])
            switch_dl_status(bvid, 0)
            dynamic_list.update({'dl_retry': 0}, where('bvid') == bvid)
    return {'code': 0, 'data': f'重新加入下载列表'}

# 修改推测bgm标题
@app.route('/api/edit.title', methods=['POST'])
def edit_title():
    js = request.json
    bvid = js['bvid']
    shazam_id = js['shazam_id']
    etitle = js['etitle']
    # shazam_id不存在，直接存储
    if shazam_id in [0, -1]:
        dynamic_list.update({'etitle': etitle}, where('bvid') == bvid)
    # shazam_id存在，修改shazam_title
    else:
        shazam_list.update({'title': etitle}, where('id') == shazam_id)
    return {'code': 0, 'data': '修改自定义标题成功'}

# 投稿youtube
@app.route('/api/upload.ytb/<bvids>')
def upload_ytb(bvids):
    for bvid in bvids.split(','):
        dynamic_list.update({'ustatus': 100}, where('bvid') == bvid)
    return {'code': 0, 'data': '添加上传任务成功'}

# 删除该动态之后所有未投稿的视频
@app.route('/api/delete.from/<pd>/to/<ts>')
def delete_from(pd, ts):
    pdate = int(pd)
    timestamp = int(ts)
    q = (where('pdate') >= pdate) & (where('pdate') <= timestamp) & (where('ustatus') == 0)
    del_list = dynamic_list.search(q)
    for item in del_list:
        find_and_remove(item['title'])
    dynamic_list.remove(q)
    return {'code': 0, 'data': f'共删除 {len(del_list)} 条动态及视频'}

if __name__ == '__main__':
    app.run(debug=DEBUG)
