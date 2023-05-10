# -*- coding: utf-8 -*-

import os
import asyncio
from datetime import datetime
from constant import *
from util import set_config, switch_dl_status, find_and_remove
from tinydb import TinyDB, Query, where
from flask import Flask, flash, request

app = Flask(__name__)

db = TinyDB(DB_PATH)
shazam_list = db.table('shazam_list', cache_size=0)
dynamic_list = db.table('dynamic_list', cache_size=0)

def add_shazam(item):
    q = where('id') == item['shazam_id']
    target = shazam_list.get(q)
    if target != None:
        return {**item, 'etitle': target['title']}
    else:
        return item

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
    # 0全部，1下载失败，2上传ytb失败
    dtype = int(request.args.get('dtype') or 0)
    # 所有失败类型
    dl_err_q = where('dstatus') < 0
    up_err_q = where('ustatus') < 0
    if dtype == 1:
        q_list = dynamic_list.search(dl_err_q)
    elif dtype == 2:
        q_list = dynamic_list.search(up_err_q)
    else:
        q_list = dynamic_list.all()
    all_list = sorted(q_list, key=lambda i: i['pdate'], reverse=True)
    total = len(all_list)
    st = (page - 1) * size
    ed = page * size
    current_list = all_list[st:ed]
    
    return {'code': 0, 'data': list(map(add_shazam, current_list)), 'total': total }

# 占用空间情况
@app.route('/api/folder.size')
def folder_size():
    def get_dir_size(path=MEDIA_ROOT):
        total = 0
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_file():
                    total += entry.stat().st_size
                elif entry.is_dir():
                    total += get_dir_size(entry.path)
        return round(total / (1024 ** 3), 2)
    
    dl_count = dynamic_list.count(where('dstatus') == 200)
    up_count = dynamic_list.count(where('ustatus') == 200)
    
    return {
        'code': 0,
        'data': {
            'size': f'{get_dir_size()}GB',
            'downloaded': dl_count,
            'uploaded': up_count,
        }
    }

# 重试下载视频
@app.route('/api/retry', methods=['POST'])
def retry_dl_video():
    bvids = request.json
    for bvid in bvids:
        target = dynamic_list.get(where('bvid') == bvid)
        if target != None:
            find_and_remove(target['title'])
            switch_dl_status(bvid, 0)
            dynamic_list.update({'dl_retry': 0}, where('bvid') == bvid)
    return {'code': 0, 'data': f'重新加入下载列表'}

# 重置BGM识别状态
@app.route('/api/reset.bgm', methods=['POST'])
def reset_bgm():
    bvids = request.json
    for bvid in bvids:
        dynamic_list.update({'shazam_id': 0}, where('bvid') == bvid)

    return {'code': 0, 'data': f'重置BGM识别状态'}

# 修改推测bgm标题
@app.route('/api/edit.title', methods=['POST'])
def edit_title():
    js = request.json
    bvid = js['bvid']
    shazam_id = js['shazam_id']
    etitle = js['etitle']
    # shazam_id不存在，直接存储
    if shazam_id in [0, -1, -2, -3]:
        dynamic_list.update({'etitle': etitle}, where('bvid') == bvid)
    # shazam_id存在，修改shazam_title
    else:
        shazam_list.update({'title': etitle}, where('id') == shazam_id)
    return {'code': 0, 'data': '修改自定义标题成功'}

# 投稿youtube
@app.route('/api/upload.ytb', methods=['POST'])
def upload_ytb():
    bvids = request.json
    for bvid in bvids:
        dynamic_list.update({'ustatus': 100}, where('bvid') == bvid)
    return {'code': 0, 'data': '添加上传任务成功'}

# 删除动态&视频
@app.route('/api/delete.video', methods=['POST'])
def delete_video():
    del_list = request.json
    for item in del_list:
        find_and_remove(item['title'])
        dynamic_list.remove(where('bvid') == item['bvid'])
    return {'code': 0, 'data': '删除投稿成功'}

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
    app.run(debug=False)
