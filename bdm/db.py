import logging
import threading

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError

from bdm import config

logger = logging.getLogger(__name__)

_client = None
_lock = threading.Lock()


def client():
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                config.require('MONGODB_URL')
                _client = MongoClient(config.MONGODB_URL, tz_aware=True)
    return _client


def database():
    return client()[config.MONGODB_DB]


def videos():
    return database().dynamic_list


def ups():
    return database().up_list


def songs():
    return database().shazam_list


def settings():
    return database().config


def task_state():
    return database().task_state


def ensure_indexes():
    specs = [
        (videos(), [('vid', ASCENDING)], {'unique': True}),
        (videos(), [('pdate', DESCENDING)], {}),
        (videos(), [('dstatus', ASCENDING), ('pdate', DESCENDING)], {}),
        (videos(), [('uid', ASCENDING), ('pdate', DESCENDING)], {}),
        (ups(), [('uid', ASCENDING)], {'unique': True}),
        (songs(), [('id', ASCENDING)], {'unique': True}),
        (task_state(), [('name', ASCENDING)], {'unique': True}),
    ]
    for coll, keys, opts in specs:
        try:
            coll.create_index(keys, **opts)
        except PyMongoError as err:
            logger.warning('创建索引失败 %s %s：%s', coll.name, keys, err)


# config 集合沿用历史结构：每个配置项一个文档，形如 {"check_point": 123}
def get_setting(key, default=None):
    doc = settings().find_one({key: {'$exists': True}})
    return doc[key] if doc else default


def set_setting(key, value):
    settings().update_one({key: {'$exists': True}}, {'$set': {key: value}}, upsert=True)
