# -*- coding: utf-8 -*-

import os
import re
import json
import time
import requests
from datetime import datetime
from constant import *
from util import find_and_remove, get_mp4_path
from flask import Flask, g, request
from pymongo import MongoClient

app = Flask(__name__)

@app.before_request
def before_request():
    """
    在请求处理函数之前打开数据库连接
    """
    
    client = MongoClient(MONGODB_URL)
    g.client = client
    g.dynamic_list = client.dance.dynamic_list
    g.config = client.dance.config
    g.shazam_list = client.dance.shazam_list
    g.follow_list = client.dance.follow_list

@app.after_request
def after_request(response):
    """
    在请求处理函数之后关闭数据库连接
    """
    g.client.close()
    return response

def add_attach(item):
    ritem = item
    # shazam
    st = g.shazam_list.find_one({"id": item['shazam_id']})
    # uname
    ut = g.follow_list.find_one({"uid": item['uid']})
    if st != None:
        ritem = {**ritem, 'etitle': st['title']}
    if ut != None:
        ritem = {**ritem, 'uname': ut['uname']}
    return ritem

def parseBV(bvid, p = 1):
    cookie = {'SESSDATA': DYNAMIC_COOKIE}
    res_view = requests.get(VIDEO_VIEW_API(bvid), cookies=cookie)
    res_json = json.loads(res_view.text)
    if res_json['code'] != 0:
        raise Exception(f'解析bvid失败')

    res_detail = requests.get(VIDEO_DETAIL_API(bvid, p))
    try:
        play_info = re.search(r'<script>window.__playinfo__=([^<]+)</script>', res_detail.text)
        pinfo = json.loads(play_info.group(1))
    except:
        raise Exception(f'解析bvid失败')

    curr_page = res_json['data']['pages'][p - 1]
    title = res_json['data']['title']
    pdate = int(time.time())
    pdstr = datetime.fromtimestamp(pdate).strftime("%Y-%m-%d %H:%M:%S")
    desc = res_json['data']['desc']
    cover = res_json['data']['pic']
    cid = curr_page['cid']
    p_title = curr_page['part']
    duration = curr_page['duration']
    mm, ss = divmod(duration, 60)
    duration_text = str(int(mm)).zfill(2) + ":" + str(int(ss)).zfill(2)
    uid = res_json['data']['owner']['mid']
    uname = res_json['data']['owner']['name']
    avatar = res_json['data']['owner']['face']
    max_quality = pinfo['data']['accept_description'][0]
    vwidth = curr_page['dimension']['width']
    vheight = curr_page['dimension']['height']
    is_portrait = 1 if (vwidth / vheight < 1) else 0
    
    return {
        'source': 1,
        'pure_vid': bvid,
        'vid': f'{bvid}[p{p}]' if p > 1 else bvid,
        'p': p,
        'cid': cid,
        'p_title': p_title,
        'uid': uid,
        'uname': uname,
        'title': title,
        'cover': cover,
        'desc': desc,
        'duration': duration,
        'duration_text': duration_text,
        'avatar': avatar,
        'pdate': pdate, 
        'pdstr': pdstr,
        'is_portrait': is_portrait,
        'max_quality': max_quality,
        'shazam_id': 0,
        'dstatus': 0,
        'dl_retry': 0,
        'ustatus': 100,
        'up_retry': 0,
    }

def parseAC(acid, p = 1):
    res_detail = requests.get(ACFUN_VIDEO_PLAY_API(acid, p), headers={"user-agent": ACFUN_USER_AGENT})
    try:
        play_info = re.search(r"window\.pageInfo\s*=\s*window\.videoInfo\s*=\s*(\{(?:(?<!\};).)*\});", res_detail.text)
        res_json = json.loads(play_info.group(1))
    except:
        raise Exception(f'解析acid失败')

    p_title = res_json['videoList'][p - 1]['title']
    title = res_json['title']
    pdate = int(time.time())
    pdstr = datetime.fromtimestamp(pdate).strftime("%Y-%m-%d %H:%M:%S")
    desc = res_json['description']
    cover = res_json['coverUrl']
    duration = res_json['videoList'][p - 1]['durationMillis'] // 1000
    mm, ss = divmod(duration ,60)
    duration_text = str(int(mm)).zfill(2) + ":" + str(int(ss)).zfill(2)
    uid = res_json['user']['id']
    uname = res_json['user']['name']
    avatar = res_json['user']['headUrl']
    max_quality = res_json['currentVideoInfo']['transcodeInfos'][0]['qualityType'].upper()
    is_portrait = int(res_json['currentVideoInfo']['sizeType']) - 1
    
    return {
        'source': 3,
        'pure_vid': acid,
        'vid': f'{acid}[p{p}]' if p > 1 else acid,
        'p': p,
        'p_title': p_title,
        'uid': uid,
        'uname': uname,
        'title': title,
        'cover': cover,
        'desc': desc,
        'duration': duration,
        'duration_text': duration_text,
        'avatar': avatar,
        'pdate': pdate, 
        'pdstr': pdstr,
        'is_portrait': is_portrait,
        'max_quality': max_quality,
        'shazam_id': 0,
        'dstatus': 0,
        'dl_retry': 0,
        'ustatus': 100,
        'up_retry': 0,
    }
    
# 托管静态资源
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    return app.send_static_file("index.html")

# 设定截止时间
@app.route('/api/init/<datestring>')
def init_cpdate(datestring):
    cpdate = int(datetime.strptime(datestring, "%Y-%m-%d %H:%M:%S").timestamp())
    g.config.update_one({"check_point": {"$exists": True}}, {"$set": {"check_point": cpdate}}, upsert=True)
    return {'code': 0, 'data': f'动态截止日期初始化为：{datestring}'}

# 探索列表
@app.route('/api/exp.list')
def explore_list():
    page = int(request.args.get('page') or 1)
    size = int(request.args.get('size') or 15)
    uid = int(request.args.get('uid') or 0)
    
    q1 = {"ustatus": {"$gt": 0}}
    q2 = {"$and": [{"uid": uid}, {"ustatus": {"$gt": 0}}]}
    q = q1 if uid == 0 else q2
    total = g.dynamic_list.count_documents(q)
    clist = g.dynamic_list.find(q, {"_id": 0}).sort([("pdate", -1)]).limit(size).skip((page - 1) * size)

    return {'code': 0, 'data': list(map(add_attach, clist)), 'total': total }

# 视频详情
@app.route('/api/video.detail/<vid>')
def video_detail(vid):
    detail = g.dynamic_list.find_one({"vid": vid}, {"_id": 0})
    try:
        local = get_mp4_path(detail)
        if local:
            linux_path = local[0]
            filesrc = linux_path.replace('/media/', 'https://bdm.src.moe:8000/file/')
            return {'code': 0, 'data': {**detail, 'filesrc': filesrc}}
    except Exception as err:
        return {'code': -2, 'data': str(err)}

# 动态列表
@app.route('/api/dyn.list')
def dyn_list():
    page = int(request.args.get('page') or 1)
    size = int(request.args.get('size') or 50)
    # 0全部，1下载失败，2上传ytb失败
    dtype = int(request.args.get('dtype') or 0)
    # 所有失败类型
    # dl_err_q = where('dstatus') < 0
    # up_err_q = where('ustatus') < 0
    if dtype == 1:
        q = {"dstatus": {"$lt": 0}}
    elif dtype == 2:
        q = {"ustatus": {"$lt": 0}}
    else:
        q = {}
    # all_list = sorted(q_list, key=lambda i: i['pdate'], reverse=True)
    total = g.dynamic_list.count_documents(q)
    # st = (page - 1) * size
    # ed = page * size
    current_list = g.dynamic_list.find(q, {"_id": 0}).sort([("pdate", -1)]).limit(size).skip((page - 1) * size)

    return {'code': 0, 'data': list(map(add_attach, current_list)), 'total': total }

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
    
    wait_count = g.dynamic_list.count_documents({"ustatus": 100})
    up_count = g.dynamic_list.count_documents({"ustatus": 200})
    
    return {
        'code': 0,
        'data': {
            'size': f'{get_dir_size()}GB',
            'waiting': wait_count,
            'uploaded': up_count,
        }
    }

# 重试下载视频
@app.route('/api/retry', methods=['POST'])
def retry_dl_video():
    vids = request.json
    for vid in vids:
        target = g.dynamic_list.find_one({"vid": vid})
        if target != None:
            find_and_remove(target)
            g.dynamic_list.update_one({"vid": vid}, {"$set": {"dstatus": 0, "dl_retry": 0}})
    return {'code': 0, 'data': f'重新加入下载列表'}

# 重置BGM识别状态
@app.route('/api/reset.bgm', methods=['POST'])
def reset_bgm():
    vids = request.json
    for vid in vids:
        g.dynamic_list.update_one({"vid": vid}, {"$set": {"shazam_id": 0}})

    return {'code': 0, 'data': f'重置BGM识别状态'}

# 重置上传状态
@app.route('/api/reset.upload', methods=['POST'])
def reset_upload():
    vids = request.json
    for vid in vids:
        g.dynamic_list.update_one({"vid": vid}, {"$set": {"ustatus": 100, "up_retry": 0}})

    return {'code': 0, 'data': f'重置上传状态成功'}

# 修改推测bgm标题
@app.route('/api/edit.title', methods=['POST'])
def edit_title():
    js = request.json
    vid = js['vid']
    shazam_id = js['shazam_id']
    etitle = js['etitle']
    # shazam_id不存在，直接存储
    if shazam_id in [0, -1, -2, -3]:
        g.dynamic_list.update_one({"vid": vid}, {"$set": {"etitle": etitle}})
    # shazam_id存在，修改shazam_title
    else:
        g.shazam_list.update_one({"id": shazam_id}, {"$set": {"title": etitle}})
    return {'code': 0, 'data': '修改自定义标题成功'}

# 投稿youtube
@app.route('/api/upload.ytb', methods=['POST'])
def upload_ytb():
    vids = request.json
    for vid in vids:
        g.dynamic_list.update_one({"vid": vid}, {"$set": {"ustatus": 100}})
    return {'code': 0, 'data': '添加上传任务成功'}

# 删除动态&视频
@app.route('/api/delete.video', methods=['POST'])
def delete_video():
    del_list = request.json
    for item in del_list:
        find_and_remove(item)
        g.dynamic_list.delete_one({"vid": item['vid']})
    return {'code': 0, 'data': '删除投稿成功'}

# 删除该动态之后所有未投稿的视频
@app.route('/api/delete.from/<pd>/to/<ts>')
def delete_from(pd, ts):
    pdate = int(pd)
    timestamp = int(ts)
    q = {"$and": [{"ustatus": 0}, {"pdate": {"$lte": timestamp}}, {"pdate": {"$gte": pdate}}]}
    # q = (where('pdate') >= pdate) & (where('pdate') <= timestamp) & (where('ustatus') == 0)
    del_list = g.dynamic_list.find(q)
    for item in del_list:
        find_and_remove(item)
    g.dynamic_list.delete_one(q)
    return {'code': 0, 'data': f'共删除 {len(del_list)} 条动态及视频'}

# 外部导入vid
@app.route('/api/add.vid', methods=['POST'])
def add_vid():
    tp = request.json['type']
    pure_vid = request.json['vid']
    p = int(request.json['p'])
    vid = f'{pure_vid}[p{p}]' if p > 1 else pure_vid
        
    # if g.history.count(where('vid') == vid):
    #     return {'code': -1, 'data': '稿件已存在'}
    if g.dynamic_list.count_documents({"vid": vid}):
        return {'code': -1, 'data': '稿件已存在'}
    try:
        if tp == 'bilibili':
            item = parseBV(pure_vid, p)
        elif tp == 'acfun':
            item = parseAC(pure_vid, p)
        else:
            raise Exception('无法解析导入的vid')
        g.dynamic_list.insert_one(item)
        
        return {'code': 0, 'data': '导入稿件成功'}
    except Exception as err:
        
        return {'code': -2, 'data': str(err)}
    
@app.route('/api/find.local', methods=['POST'])
def find_local():
    item = request.json
    try:
        local = get_mp4_path(item)
        if local:
            linux_path = local[0]
            windows_path = linux_path.replace('/media/', '')
            return {'code': 0, 'data': windows_path}
    except Exception as err:
        return {'code': -2, 'data': str(err)}

if __name__ == '__main__':
    app.run(debug=False)
