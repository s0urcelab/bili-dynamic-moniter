# -*- coding: utf-8 -*-

import os
import re
import json
import time
import threading
import requests
from datetime import datetime, timedelta, timezone
from constant import *
from util import find_and_remove, get_mp4_path, get_cover_path
from flask import Flask, g, request, jsonify
from pymongo import MongoClient
from cloud189 import Cloud189

from flask_jwt_extended import create_access_token
from flask_jwt_extended import get_jwt
from flask_jwt_extended import get_jwt_identity
from flask_jwt_extended import jwt_required
from flask_jwt_extended import JWTManager
from flask_jwt_extended import set_access_cookies
from flask_jwt_extended import unset_jwt_cookies
            
app = Flask(__name__)

app.client189 = Cloud189({
    'username': CLOUD189_USERNAME,
    'password': CLOUD189_PASSWORD
})
# app.client189 = {}
# app.client189 = Cloud189(cookies=CLOUD189_COOKIES)
app.start_event = threading.Event()
app.err_msg = ''
app.err_item = ''

# If true this will only allow the cookies that contain your JWTs to be sent
# over https. In production, this should always be set to True
app.config["JWT_COOKIE_SECURE"] = True
app.config["JWT_COOKIE_CSRF_PROTECT"] = False
app.config["JWT_SESSION_COOKIE"] = False
app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
app.config["JWT_SECRET_KEY"] = JWT_SECRET_KEY
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(weeks=2)

jwt = JWTManager(app)

"""
单开一个线程执行历史视频上传
"""
def upload_task(app):
    client = MongoClient(MONGODB_URL)
    while app.start_event.is_set():
        q = {"$and": [{"ustatus": {"$gt": USTATUS.DEFAULT}}, {"dstatus": DSTATUS.LOCAL}, {'fid': {'$exists': False}}]}
        all_res = client.dance.dynamic_list.find(q, {"_id": 0}).sort([("pdate", 1)])
        item = next(all_res, None)
        if item:
            # 封面
            try:
                cover_files = get_cover_path(item)
                cover_fid = app.client189.upload(cover_files[0], CLOUD189_TARGET_FOLDER_ID, item['vid'])
            except:
                pass
            else:
                client.dance.dynamic_list.update_one({"vid": item['vid']}, {"$set": {"cover_fid": cover_fid}})
                
            # 视频
            try:
                mp4_files = get_mp4_path(item)
                fid = app.client189.upload(mp4_files[0], CLOUD189_TARGET_FOLDER_ID, item['vid'])
            except Exception as err:
                app.start_event.clear()
                app.err_item = f'[{item["vid"]}] {item["title"]}'
                app.err_msg = repr(err)
            else:
                client.dance.dynamic_list.update_one({"vid": item['vid']}, {"$set": {"dstatus": DSTATUS.CLOUD189, "fid": fid}})
                find_and_remove(item)
        else:
            # 没有新的待上传，等待5分钟重试
            time.sleep(300)
    
    client.close()

@app.after_request
def refresh_expiring_jwts(response):
    """
    刷新jwt
    """
    try:
        exp_timestamp = get_jwt()["exp"]
        now = datetime.now(timezone.utc)
        target_timestamp = datetime.timestamp(now + timedelta(days=1))
        if target_timestamp > exp_timestamp:
            access_token = create_access_token(identity=get_jwt_identity())
            set_access_cookies(response, access_token)
        return response
    except (RuntimeError, KeyError):
        # Case where there is not a valid JWT. Just return the original response
        return response
    
@app.route("/api/admin.login", methods=["POST"])
def login():
    p = request.json
    if p['pw'] == MANAGE_PASSWORD:
        response = jsonify({'code': 0, 'data': '登录成功'})
        access_token = create_access_token(identity="admin")
        set_access_cookies(response, access_token)
        return response
    return {'code': -300, 'data': '登录失败'}


@app.route("/api/admin.logout", methods=["POST"])
@jwt_required()
def logout():
    response = jsonify({'code': 0, 'data': '登出成功'})
    unset_jwt_cookies(response)
    return response

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
    g.up_list = client.dance.up_list

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
    ut = g.up_list.find_one({"uid": item['uid']})
    if st != None:
        ritem = {**ritem, 'etitle': st['title']}
    if ut != None:
        ritem = {**ritem, 'uname': ut['uname'], 'usign': ut['sign'], 'avatar': ut['avatar']}
    return ritem

def parseBV(bvid, p = 1):
    max_quality = '未知'
    res_view = requests.get(VIDEO_VIEW_API(bvid), headers={"user-agent": FAKE_USER_AGENT})
    res_json = json.loads(res_view.text)
    if res_json['code'] != 0:
        raise Exception(f'解析bvid失败:web_interface')
    
    curr_page = res_json['data']['pages'][p - 1]
    cid = curr_page['cid']
    
    playurl = requests.get(VIDEO_PLAYURL_API(bvid, cid), headers={"user-agent": FAKE_USER_AGENT, "referer": FAKE_REFERER})
    playurl_json = json.loads(playurl.text)
    if playurl_json['code'] != 0:
        raise Exception(f'解析bvid失败:playurl_api')
    
    max_quality = playurl_json['data']['accept_description'][0]
    
    title = res_json['data']['title']
    pdate = int(time.time())
    pdstr = datetime.fromtimestamp(pdate).strftime("%Y-%m-%d %H:%M:%S")
    desc = res_json['data']['desc']
    cover = res_json['data']['pic']
    p_title = curr_page['part']
    duration = curr_page['duration']
    mm, ss = divmod(duration, 60)
    duration_text = str(int(mm)).zfill(2) + ":" + str(int(ss)).zfill(2)
    uid = res_json['data']['owner']['mid']
    uname = res_json['data']['owner']['name']
    avatar = res_json['data']['owner']['face']
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
        'ustatus': USTATUS.SELECTED,
        'up_retry': 0,
    }

def parseAC(acid, p = 1):
    res_detail = requests.get(ACFUN_VIDEO_PLAY_API(acid, p), headers={"user-agent": FAKE_USER_AGENT})
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
    uid = int(res_json['user']['id'])
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
        'ustatus': USTATUS.SELECTED,
        'up_retry': 0,
    }
    
# 托管静态资源
# @app.route('/', defaults={'path': ''})
# @app.route('/<path:path>')
# def catch_all(path):
#     return app.send_static_file("index.html")

# 设定截止时间
@app.route('/api/init/<datestring>')
@jwt_required()
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
    
    q1 = {"$and": [{"ustatus": {"$gt": USTATUS.DEFAULT}}, {"dstatus": {"$gte": DSTATUS.LOCAL}}]}
    q2 = {"$and": [{"uid": uid}, {"ustatus": {"$gt": USTATUS.DEFAULT}}, {"dstatus": {"$gte": DSTATUS.LOCAL}}]}
    q = q1 if uid == 0 else q2
    total = g.dynamic_list.count_documents(q)
    clist = g.dynamic_list.find(q, {"_id": 0}).sort([("pdate", -1)]).limit(size).skip((page - 1) * size)

    return {'code': 0, 'data': list(map(add_attach, clist)), 'total': total }

# 视频详情
@app.route('/api/video.detail/<vid>')
def video_detail(vid):
    detail = g.dynamic_list.find_one({"vid": vid}, {"_id": 0})
    q = {"$and": [{"uid": detail['uid']}, {"vid": { "$ne": vid }}, {"ustatus": {"$gt": USTATUS.DEFAULT}}]}
    q_list = g.dynamic_list.find(q, {"_id": 0}).limit(6)
    more_list = list(map(add_attach, q_list))
    try:
        local = get_mp4_path(detail)
        if 'fid' in detail and detail['fid']:
            play_url = app.client189.get_play_url(detail['fid'])
            return {'code': 0, 'data': {**add_attach(detail), 'filesrc': play_url}, 'more': list(more_list)}
        if local:
            linux_path = local[0]
            filesrc = linux_path.replace('/media/', 'https://rcc.src.moe:8000/file/')
            return {'code': 0, 'data': {**add_attach(detail), 'filesrc': filesrc}, 'more': list(more_list)}
    except Exception as err:
        return {'code': -2, 'data': str(err)}

# 查询
@app.route('/api/fuzzy.search')
def fuzzy_search():
    keyword = request.args.get('keyword')
    
    if not keyword:
        return {'code': -5, 'data': '未传入关键词'}
    
    regex = f'.*{keyword}.*'
    qre = {'$regex': regex, '$options': 'i'}
    u_res = g.up_list.find({'uname': qre}, {'_id': 0})
    sz_list = list(map(lambda i: i['id'], g.shazam_list.find({'title': qre}, {'_id': 0})))
    dq = {"$and": [{"ustatus": {"$gt": USTATUS.DEFAULT}}, {"dstatus": {"$gte": DSTATUS.LOCAL}}, {'$or': [{'shazam_id': {'$in': sz_list}}, {'title': qre}, {'etitle': qre}]}]}
    d_res = g.dynamic_list.find(dq, {'_id': 0})
    
    return {'code': 0, 'data': { 'ups': list(u_res), 'videos': list(map(add_attach, d_res))[:50] }}

# UP主详情
@app.route('/api/up.info/<uid>')
def get_up_info(uid):
    up_info = g.up_list.find_one({"uid": int(uid)}, {"_id": 0})
    
    return {'code': 0, 'data': up_info}

# 动态列表
@app.route('/api/dyn.list')
@jwt_required()
def dyn_list():
    keyword = request.args.get('keyword')
    
    page = int(request.args.get('page') or 1)
    size = int(request.args.get('size') or 50)
    # 0全部，1下载失败，2上传ytb失败
    dtype = int(request.args.get('dtype') or 0)
    uid = int(request.args.get('uid') or 0)
    # 所有失败类型
    # dl_err_q = where('dstatus') < 0
    # up_err_q = where('ustatus') < 0
    # 管理页查询
    if uid == 0 and keyword:
        regex = f'.*{keyword}.*'
        qre = {'$regex': regex, '$options': 'i'}
        u_res = g.up_list.find({'uname': qre}, {'_id': 0})
        sz_list = list(map(lambda i: i['id'], g.shazam_list.find({'title': qre}, {'_id': 0})))
        dq = {"$and": [{'$or': [{'vid': keyword}, {'shazam_id': {'$in': sz_list}}, {'title': qre}, {'etitle': qre}]}]}
        d_res = g.dynamic_list.find(dq, {'_id': 0}).sort([("pdate", -1)]).limit(size).skip((page - 1) * size)
        total = g.dynamic_list.count_documents(dq)
        
        return {'code': 0, 'data': list(map(add_attach, d_res)), 'total': total, 'ups': list(u_res) }
    
    if dtype == 1:
        q = {"dstatus": {"$lt": DSTATUS.DEFAULT}}
    elif dtype == 2:
        q = {"ustatus": {"$lt": USTATUS.DEFAULT}}
    elif uid != 0:
        q = {"uid": uid}
    else:
        q = {}
    # all_list = sorted(q_list, key=lambda i: i['pdate'], reverse=True)
    total = g.dynamic_list.count_documents(q)
    # st = (page - 1) * size
    # ed = page * size
    current_list = g.dynamic_list.find(q, {"_id": 0}).sort([("pdate", -1)]).limit(size).skip((page - 1) * size)

    return {'code': 0, 'data': list(map(add_attach, current_list)), 'total': total }

# 重置后台独立线程任务
@app.route('/api/toggle.bgtask')
@jwt_required()
def toggle_bg_task():
    status = request.args.get('status')
    if status == 'on':
        app.start_event.set()
        threading.Thread(target=upload_task, args=(app,), daemon=True).start()
    elif status == 'off':
        app.start_event.clear()
    else:
        pass
    return {'code': 0, 'data': f'后台任务{"启动" if app.start_event.is_set() else "停止"}'}
    
# 占用空间情况
@app.route('/api/folder.size')
@jwt_required()
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
    
    # wait_count = g.dynamic_list.count_documents({"ustatus": USTATUS.SELECTED})
    # up_count = g.dynamic_list.count_documents({"ustatus": USTATUS.UPLOADED})
    
    cloud_size = ''
    try:
        cloud_disk = app.client189.get_disk_space_info()
        used_size = cloud_disk["cloudCapacityInfo"]["usedSize"]
        total_size = cloud_disk["cloudCapacityInfo"]["totalSize"]
        cloud_size = f'{round(used_size / (1024 ** 4), 2)} / {round(total_size / (1024 ** 4), 2)}TB'
    except:
        cloud_size = '未知'
    
    return {
        'code': 0,
        'data': {
            'local_size': f'{get_dir_size()}GB',
            'cloud_size': cloud_size,
            # 'waiting': wait_count,
            # 'uploaded': up_count,
            'is_bg_task_running': app.start_event.is_set(),
            'task_err_msg': app.err_msg,
            'task_err_item': app.err_item,
        }
    }

# 重试下载视频
@app.route('/api/retry', methods=['POST'])
@jwt_required()
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
@jwt_required()
def reset_bgm():
    vids = request.json
    for vid in vids:
        g.dynamic_list.update_one({"vid": vid}, {"$set": {"shazam_id": 0}})

    return {'code': 0, 'data': f'重置BGM识别状态'}

# 重置上传状态
@app.route('/api/reset.upload', methods=['POST'])
@jwt_required()
def reset_upload():
    vids = request.json
    for vid in vids:
        g.dynamic_list.update_one({"vid": vid}, {"$set": {"ustatus": USTATUS.SELECTED, "up_retry": 0}})

    return {'code': 0, 'data': f'重置上传状态成功'}

# 修改推测bgm标题
@app.route('/api/edit.title', methods=['POST'])
@jwt_required()
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

# 精选投稿
@app.route('/api/upload.ytb', methods=['POST'])
@jwt_required()
def upload_ytb():
    vids = request.json
    for vid in vids:
        g.dynamic_list.update_one({"vid": vid}, {"$set": {"ustatus": USTATUS.SELECTED}})
    # return {'code': 0, 'data': '添加上传任务成功'}
    return {'code': 0, 'data': '精选投稿成功'}

# 删除动态&视频
@app.route('/api/delete.video', methods=['POST'])
@jwt_required()
def delete_video():
    del_list = request.json
    for item in del_list:
        find_and_remove(item, app.client189)
        g.dynamic_list.delete_one({"vid": item['vid']})
    return {'code': 0, 'data': '删除投稿成功'}

# 删除该动态之后所有未投稿的视频
@app.route('/api/delete.batch', methods=['POST'])
def delete_from():
    js = request.json
    uid = js.get('uid')
    pdate = int(js.get('pd'))
    timestamp = int(js.get('ts'))
    q1 = {"ustatus": USTATUS.DEFAULT}
    q2 = {"pdate": {"$lte": timestamp}}
    q3 = {"pdate": {"$gte": pdate}}
    q = {"$and": [q1, q2, q3]}
    if uid:
        q = {"$and": [q1, q2, q3, {"uid": int(uid)}]}
    del_list = g.dynamic_list.find(q)
    for item in del_list:
        find_and_remove(item, app.client189)
    result = g.dynamic_list.delete_many(q)
    return {'code': 0, 'data': f'共删除 {result.deleted_count} 条动态及视频'}

# 外部导入vid
@app.route('/api/add.vid', methods=['POST'])
@jwt_required()
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
    try:
        item = request.json
        if 'fid' in item and item['fid']:
            play_url = app.client189.get_play_url(item['fid'])
            return {'code': 0, 'data': play_url}
        local = get_mp4_path(item)
        if local:
            linux_path = local[0]
            windows_path = linux_path.replace('/media/', 'https://rcc.src.moe:8000/file/')
            return {'code': 0, 'data': windows_path}
        else:
            return {'code': -3, 'data': '文件不存在'}
    except Exception as err:
        return {'code': -2, 'data': str(err)}
    


if __name__ == '__main__':
    app.run(debug=False)
    # print(parseBV('BV15i4y1B7DF'))
