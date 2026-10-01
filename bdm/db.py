"""
SQLite 存储。API 的各个 worker、调度进程和阶段子进程共用同一个数据库文件。
WAL 模式下读写互不阻塞；同一时刻只有一个写者，其余写入最多等待 BUSY_TIMEOUT 秒。

稿件按列存储，读出时还原成接口中的稿件对象（dict）：
    - 值为 NULL 的列视为字段不存在，不出现在 dict 中
    - shazam_id 存为 bgm_status + song_id：识别出曲目时 bgm_status 为 BGM_MATCHED，否则为 ShazamStatus 中的值
    - source 为字符串的历史数据（本地手动下载）存在 local_tag 中，此时 source 列为 NULL
    - pdstr 由 pdate 按 TZ 计算，不落库
写入时同样接受这些字段名，由 encode_video 转换为列。
"""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from bdm import config
from bdm.status import DStatus, ShazamStatus, UStatus

BUSY_TIMEOUT = 15
SCHEMA_VERSION = 1
BGM_MATCHED = 1

# 已发布：精选且本地/云盘。查询中必须原样使用这段文本才能命中下面的部分索引；
# +dstatus 阻止优化器改用 videos_dstatus_pdate（它要回表检查一半的稿件，慢两个数量级）
PUBLISHED = f'ustatus > {UStatus.DEFAULT} AND +dstatus >= {DStatus.LOCAL}'

SCHEMA = [
    f"""
    CREATE TABLE videos (
        vid             TEXT PRIMARY KEY,
        source          INTEGER,
        local_tag       TEXT,
        uid             INTEGER NOT NULL,
        uname           TEXT NOT NULL,
        avatar          TEXT NOT NULL DEFAULT '',
        title           TEXT NOT NULL,
        "desc"          TEXT,
        cover           TEXT NOT NULL DEFAULT '',
        pdate           INTEGER NOT NULL,
        duration        INTEGER NOT NULL DEFAULT 0,
        duration_text   TEXT,
        max_quality     TEXT,
        is_portrait     INTEGER,
        cid             INTEGER,
        pure_vid        TEXT,
        p               INTEGER,
        p_title         TEXT,
        ytb_id          TEXT,
        ustatus         INTEGER NOT NULL DEFAULT {UStatus.DEFAULT},
        dstatus         INTEGER NOT NULL DEFAULT {DStatus.PENDING},
        dl_retry        INTEGER NOT NULL DEFAULT 0,
        dl_error        TEXT,
        dl_requested    INTEGER,
        low_res         INTEGER,
        video_info      TEXT,
        downloaded_at   TEXT,
        cloud_retry     INTEGER NOT NULL DEFAULT 0,
        cloud_error     TEXT,
        fid             TEXT,
        cover_fid       TEXT,
        stale_fid       TEXT,
        stale_cover_fid TEXT,
        uploaded_at     TEXT,
        up_retry        INTEGER NOT NULL DEFAULT 0,
        bgm_status      INTEGER NOT NULL DEFAULT {ShazamStatus.PENDING},
        song_id         TEXT REFERENCES songs (id),
        etitle          TEXT,
        CHECK ((source IS NULL) <> (local_tag IS NULL)),
        CHECK ((bgm_status = {BGM_MATCHED}) = (song_id IS NOT NULL)),
        CHECK (video_info IS NULL OR json_valid(video_info))
    ) STRICT
    """,
    'CREATE INDEX videos_pdate ON videos (pdate DESC)',
    'CREATE INDEX videos_dstatus_pdate ON videos (dstatus, pdate DESC)',
    'CREATE INDEX videos_uid_pdate ON videos (uid, pdate DESC)',
    f'CREATE INDEX videos_published ON videos (pdate DESC) WHERE {PUBLISHED}',
    f'CREATE INDEX videos_published_uid ON videos (uid, pdate DESC) WHERE {PUBLISHED}',
    'CREATE INDEX videos_song ON videos (song_id) WHERE song_id IS NOT NULL',
    """
    CREATE TABLE ups (
        uid     INTEGER PRIMARY KEY,
        uname   TEXT NOT NULL,
        avatar  TEXT NOT NULL DEFAULT '',
        sign    TEXT NOT NULL DEFAULT ''
    ) STRICT
    """,
    """
    CREATE TABLE songs (
        id      TEXT PRIMARY KEY,
        title   TEXT NOT NULL
    ) STRICT, WITHOUT ROWID
    """,
    """
    CREATE TABLE settings (
        key     TEXT PRIMARY KEY,
        value   TEXT NOT NULL CHECK (json_valid(value))
    ) STRICT, WITHOUT ROWID
    """,
    """
    CREATE TABLE task_state (
        name                    TEXT PRIMARY KEY,
        enabled                 INTEGER NOT NULL DEFAULT 1,
        paused_reason           TEXT,
        run_requested           INTEGER NOT NULL DEFAULT 0,
        running                 INTEGER NOT NULL DEFAULT 0,
        last_started_at         TEXT,
        last_finished_at        TEXT,
        last_status             TEXT,
        last_summary            TEXT,
        last_error              TEXT,
        last_error_item         TEXT,
        last_error_at           TEXT,
        error_in_run            INTEGER NOT NULL DEFAULT 0,
        consecutive_failures    INTEGER NOT NULL DEFAULT 0,
        updated_at              TEXT
    ) STRICT, WITHOUT ROWID
    """,
]

_local = threading.local()


# ---------- 连接与事务 ----------

def _icontains(haystack, needle):
    return haystack is not None and needle.casefold() in haystack.casefold()


def connect(path=None):
    path = path or config.DB_PATH
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA synchronous = NORMAL')
    # 不区分大小写的字面匹配；LIKE 只对 ASCII 忽略大小写，且需要转义 % 和 _
    conn.create_function('icontains', 2, _icontains, deterministic=True)
    return conn


def conn():
    """当前线程（gevent 下为当前协程）的连接。"""
    c = getattr(_local, 'conn', None)
    if c is None:
        c = _local.conn = connect()
    return c


def close():
    c = getattr(_local, 'conn', None)
    if c is not None:
        _local.conn = None
        c.close()


@contextmanager
def transaction():
    """
    写事务。事务内不能有网络请求、sleep 等会让出 gevent 协程的操作：SQLite 等锁时阻塞整个线程，
    让出后同进程的其他协程再申请写锁会一直等到 BUSY_TIMEOUT。
    """
    c = conn()
    c.execute('BEGIN IMMEDIATE')
    try:
        yield c
    except BaseException:
        c.execute('ROLLBACK')
        raise
    c.execute('COMMIT')


def init():
    """建表（幂等）。API 与 worker 启动时各调用一次。"""
    c = conn()
    c.execute('PRAGMA journal_mode = WAL')
    with transaction():
        version = c.execute('PRAGMA user_version').fetchone()[0]
        if version == SCHEMA_VERSION:
            return
        if version != 0:
            raise RuntimeError(f'数据库结构版本 {version} 与程序（{SCHEMA_VERSION}）不一致')
        for statement in SCHEMA:
            c.execute(statement)
        c.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')


def execute(sql, params=()):
    return conn().execute(sql, params)


def query(sql, params=()):
    return [dict(row) for row in conn().execute(sql, params)]


def query_one(sql, params=()):
    row = conn().execute(sql, params).fetchone()
    return dict(row) if row else None


def scalar(sql, params=()):
    row = conn().execute(sql, params).fetchone()
    return row[0] if row else None


def marks(values):
    """IN 子句的占位符。"""
    return ', '.join('?' * len(values))


# ---------- 值转换 ----------

def to_db_time(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def from_db_time(text):
    return datetime.fromisoformat(text)


def _json_default(o):
    if isinstance(o, datetime):
        return {'$date': to_db_time(o)}
    raise TypeError(f'无法序列化 {type(o).__name__}')


def _json_hook(d):
    if len(d) == 1 and '$date' in d:
        return from_db_time(d['$date'])
    return d


def dumps(value):
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def loads(text):
    return json.loads(text, object_hook=_json_hook)


_ENCODE = {
    'int': int,
    'text': str,
    'bool': lambda v: int(bool(v)),
    'json': dumps,
    'time': to_db_time,
}

_DECODE = {
    'int': lambda v: v,
    'text': lambda v: v,
    'bool': bool,
    'json': loads,
    'time': from_db_time,
}


def encode(kind, value):
    return None if value is None else _ENCODE[kind](value)


def decode(kind, value):
    return None if value is None else _DECODE[kind](value)


# ---------- 设置（键值） ----------

def get_setting(key, default=None):
    text = scalar('SELECT value FROM settings WHERE key = ?', (key,))
    return default if text is None else loads(text)


def set_setting(key, value):
    execute('INSERT INTO settings (key, value) VALUES (?, ?) '
            'ON CONFLICT (key) DO UPDATE SET value = excluded.value', (key, dumps(value)))


def delete_settings(*keys):
    execute(f'DELETE FROM settings WHERE key IN ({marks(keys)})', keys)


# ---------- 稿件 ----------

VIDEO_FIELDS = {
    'vid': 'text', 'uid': 'int', 'uname': 'text', 'avatar': 'text',
    'title': 'text', 'desc': 'text', 'cover': 'text', 'pdate': 'int',
    'duration': 'int', 'duration_text': 'text', 'max_quality': 'text', 'is_portrait': 'int',
    'cid': 'int', 'pure_vid': 'text', 'p': 'int', 'p_title': 'text', 'ytb_id': 'text',
    'ustatus': 'int', 'dstatus': 'int',
    'dl_retry': 'int', 'dl_error': 'text', 'dl_requested': 'bool',
    'low_res': 'bool', 'video_info': 'json', 'downloaded_at': 'time',
    'cloud_retry': 'int', 'cloud_error': 'text',
    'fid': 'text', 'cover_fid': 'text', 'stale_fid': 'text', 'stale_cover_fid': 'text', 'uploaded_at': 'time',
    'up_retry': 'int', 'etitle': 'text',
}

_SHAZAM_STATES = {ShazamStatus.PENDING, ShazamStatus.NO_MATCH, ShazamStatus.NO_FILE, ShazamStatus.ERROR}


def encode_video(fields):
    """稿件字段 -> {列名: 值}。"""
    cols = {}
    for key, value in fields.items():
        if key == 'pdstr':
            continue
        if key == 'source':
            is_tag = isinstance(value, str)
            cols['source'] = None if is_tag else int(value)
            cols['local_tag'] = value if is_tag else None
        elif key == 'shazam_id':
            is_song = value not in _SHAZAM_STATES
            cols['bgm_status'] = BGM_MATCHED if is_song else int(value)
            cols['song_id'] = str(value) if is_song else None
        elif key in VIDEO_FIELDS:
            cols[key] = encode(VIDEO_FIELDS[key], value)
        else:
            raise KeyError(f'未知的稿件字段：{key}')
    return cols


def decode_video(row):
    row = dict(row)
    doc = {}
    for key, kind in VIDEO_FIELDS.items():
        value = row[key]
        if value is not None:
            doc[key] = decode(kind, value)
    doc['source'] = row['local_tag'] if row['source'] is None else row['source']
    doc['shazam_id'] = row['song_id'] if row['bgm_status'] == BGM_MATCHED else row['bgm_status']
    doc['pdstr'] = datetime.fromtimestamp(row['pdate'], config.TZ).strftime('%Y-%m-%d %H:%M:%S')
    return doc


def _q(column):
    return f'"{column}"'


def find_videos(where='1', params=(), order='pdate DESC', limit=None, offset=0):
    sql = f'SELECT * FROM videos WHERE {where} ORDER BY {order}'
    if limit is not None or offset:
        sql += f' LIMIT {-1 if limit is None else int(limit)} OFFSET {int(offset)}'
    return [decode_video(row) for row in conn().execute(sql, params)]


def find_video(where, params=()):
    rows = find_videos(where, params, limit=1)
    return rows[0] if rows else None


def get_video(vid):
    return find_video('vid = ?', (vid,))


def count_videos(where='1', params=()):
    return scalar(f'SELECT COUNT(*) FROM videos WHERE {where}', params)


def insert_video(doc):
    """vid 已存在时不写入，返回 False。"""
    cols = encode_video(doc)
    names = ', '.join(_q(c) for c in cols)
    cur = execute(f'INSERT INTO videos ({names}) VALUES ({marks(cols)}) ON CONFLICT (vid) DO NOTHING',
                  tuple(cols.values()))
    return cur.rowcount == 1


def insert_videos(docs):
    with transaction():
        return sum(insert_video(doc) for doc in docs)


def update_videos(where, params=(), set=None, unset=(), inc=None, only_changed=True):
    """
    更新满足 where 的稿件，返回受影响的行数。unset 为要清空的字段名，inc 为 {字段: 增量}。
    only_changed 时跳过已经是目标值的行，返回值等同于"实际被修改"的行数。
    """
    cols = encode_video(set or {})
    for key in unset:
        if key not in VIDEO_FIELDS:
            raise KeyError(f'无法清空字段：{key}')
        cols[key] = None
    assign = [f'{_q(c)} = ?' for c in cols]
    values = list(cols.values())
    for key, step in (inc or {}).items():
        assign.append(f'{_q(key)} = {_q(key)} + ?')
        values.append(step)
    if not assign:
        return 0

    sql = f'UPDATE videos SET {", ".join(assign)} WHERE ({where})'
    values.extend(params)
    if only_changed and not inc and cols:
        sql += ' AND NOT (' + ' AND '.join(f'{_q(c)} IS ?' for c in cols) + ')'
        values.extend(cols.values())
    return execute(sql, values).rowcount


def delete_video(vid):
    execute('DELETE FROM videos WHERE vid = ?', (vid,))
