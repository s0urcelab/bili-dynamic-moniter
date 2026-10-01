# API 文档

服务默认监听 `:7002`，所有接口都以 `/api` 为前缀。

## 通用约定

### 响应格式

所有接口都返回 JSON，结构统一：

```json
{ "code": 0, "message": "ok", "data": {} }
```

- 成功时 `code` 为 `0`，HTTP 状态码为 200。
- 失败时 `code` 与 HTTP 状态码相同（400 / 401 / 404 / 409 / 500 / 502），`message` 是可直接展示给用户的中文说明，`data` 为 `null`。
- 时间字段（如 `last_started_at`）为 ISO 8601 字符串，带时区。`pdate` 等来自 B 站的发布时间仍是秒级时间戳。

### 鉴权

- 管理接口（`/api/admin/*`）需要登录。登录后服务端通过 `access_token_cookie` 这个 Cookie 保存 JWT，前端请求时带上 Cookie 即可（`fetch` 需要 `credentials: 'include'`）。
- Token 有效期 2 周；剩余不足 1 天时，任意已登录请求都会自动续期。
- 未登录或登录失效时返回 401。
- 生产环境 Cookie 带 `Secure` 属性，必须通过 HTTPS 访问。本地调试可以设置 `JWT_COOKIE_SECURE=false`。

### 分页

分页接口的参数为 `page`（从 1 开始）和 `size`，返回：

```json
{ "items": [], "total": 123, "page": 1, "size": 15 }
```

### 稿件对象（Video）

列表和详情中的稿件字段如下。字段名沿用数据库，另外附加了 `bgm_title`、`up`、`selected`、`dstatus_label` 四个计算字段。

| 字段 | 说明 |
| --- | --- |
| `vid` | 稿件唯一 id。B 站为 BV 号，分 P 形如 `BV1xx[p2]`；AcFun 为 ac 号 |
| `pure_vid` / `p` | 仅手动导入的稿件有：原始 id 与分 P |
| `source` | 来源：`1` 导入 B 站，`2` 动态，`3` 导入 AcFun；`0` 或字符串为历史数据 |
| `title` / `desc` / `cover` | 标题、简介、封面地址 |
| `uid` / `uname` / `avatar` | 发布者 |
| `pdate` / `pdstr` | 发布时间（秒级时间戳 / 格式化字符串） |
| `duration` / `duration_text` | 时长（秒 / `mm:ss`） |
| `max_quality` | 稿件的最高画质描述，如 `1080P 高清` |
| `is_portrait` | `1` 为竖屏 |
| `ustatus` | `0` 普通，`100` 精选（`200` 为历史数据，也视为精选） |
| `dstatus` | 下载流水线状态，见下表 |
| `dl_retry` / `dl_error` | 下载失败次数 / 最近一次下载错误 |
| `cloud_retry` / `cloud_error` | 上传失败次数 / 最近一次上传错误 |
| `fid` / `cover_fid` | 云盘上的视频 / 封面文件 id |
| `stale_fid` / `stale_cover_fid` | 已被新版本替换、等待在上传新版本前删除的云盘旧文件 |
| `dl_requested` | 后台手动要求重新下载，完成前一直为 `true` |
| `shazam_id` | BGM 识别结果：`0` 待识别，`-1` 无匹配，`-2` 无本地文件，`-3` 识别出错，其他为 Shazam 曲目 id |
| `etitle` | 手动填写的 BGM 标题（仅在没有 Shazam 曲目时使用） |
| `video_info` | 下载后实测的 `{width, height, bitrate, fps}` |
| `low_res` | 达到重试上限、分辨率仍不达标而被保留的文件 |
| `downloaded_at` / `uploaded_at` | 下载 / 上传完成时间 |
| `bgm_title` | 计算字段：Shazam 曲目标题，没有时取 `etitle` |
| `up` | 计算字段：`{uid, uname, avatar, sign}`，优先取关注列表中的最新信息 |
| `selected` | 计算字段：是否精选 |
| `dstatus_label` | 计算字段：`dstatus` 的中文说明 |

`dstatus` 取值：

| 值 | 含义 | 后续 |
| --- | --- | --- |
| `0` | 待下载 | 下载阶段拾取 |
| `100` | 下载中 | |
| `200` | 本地（文件就绪） | 上传和识别阶段拾取，两者都完成后变为 `201` |
| `201` | 云盘（本地文件已清理） | |
| `-1` | 下载失败 | 自动重试，直到 `dl_retry` 达到上限 |
| `-2` | 文件缺失 | 同上 |
| `-3` | 分辨率不达标，本地保留目前最好的版本 | 同上；重试用尽后使用最好的版本并标记 `low_res` |

重新下载的新版本会先存到临时目录，只有本地没有旧文件、新版本达标，或者新版本分辨率不低于旧版本时，才替换旧文件。下载失败时已有的本地文件保持不动。重试用尽时，如果本地有旧版本，就用它进入 `200`；如果只有云盘上有，就恢复为 `201`。因此稿件被作者删除后，已经下载过的版本不会丢。
| `-9` | 获取详情失败 | 不自动重试 |
| `-11` | 充电专属 | 不自动重试 |

前台只展示"精选且本地/云盘"（`ustatus > 0` 且 `dstatus >= 200`）的稿件，下文称为**已发布**。

---

## 认证

### `POST /api/auth/login`

请求体：`{ "password": "..." }`

成功后设置登录 Cookie，返回 `{ "logged_in": true }`。密码错误返回 401。

### `POST /api/auth/logout`

清除登录 Cookie。

### `GET /api/auth/me`

返回 `{ "logged_in": true | false }`，可用于前端判断是否显示管理入口。

---

## 前台接口（无需登录）

### `GET /api/videos`

已发布稿件列表，按发布时间倒序。

| 参数 | 说明 |
| --- | --- |
| `page` | 默认 1 |
| `size` | 默认 15，最大 50 |
| `uid` | 可选，只看某个 UP 主 |

返回分页结构，`items` 为稿件对象数组。

### `GET /api/videos/<vid>`

稿件详情。未登录时只能查看已发布稿件，登录后可查看任意稿件。

```json
{
  "video": {},
  "play_url": "https://...",
  "play_error": null,
  "related": []
}
```

- `play_url`：优先返回云盘播放地址；还没上传时返回本地文件地址（需要配置 `LOCAL_FILE_URL_PREFIX`）。
- `play_error`：拿不到播放地址时的原因，此时 `play_url` 为 `null`。
- `related`：同一 UP 主的其他已发布稿件，最多 6 个。

### `GET /api/search?keyword=...`

在已发布稿件的标题、BGM 标题中搜索，同时搜索 UP 主昵称。不区分大小写，关键词按字面匹配。

```json
{ "ups": [], "videos": [] }
```

`ups` 最多 20 个，`videos` 最多 50 个。

### `GET /api/ups`

有已发布稿件的 UP 主列表。没有已发布稿件的 UP 主不返回。

| 参数 | 说明 |
| --- | --- |
| `page` | 默认 1 |
| `size` | 默认 20，最大 100 |
| `sort` | `recent`（默认）按最新已发布稿件的发布时间倒序；`count` 按已发布稿件数倒序。两种排序相同时按 `uid` 升序，保证翻页稳定 |

返回分页结构，`items` 中每一项为：

```json
{ "uid": 123456, "uname": "...", "avatar": "https://...", "sign": "...", "video_count": 42, "latest_at": 1727780000 }
```

- `video_count`：已发布稿件数。
- `latest_at`：最新已发布稿件的 `pdate`（秒级时间戳）。

前台首页只取第一页展示"最近更新的 UP 主"，完整列表在 `/ups` 页面无限滚动加载。

### `GET /api/ups/<uid>`

UP 主信息：`{ uid, uname, avatar, sign, video_count, latest_at }`，字段含义同上。

- 已关注但还没有已发布稿件的 UP 主也会返回，此时 `video_count` 为 `0`，`latest_at` 为 `null`。
- 昵称和头像优先取关注列表；不在关注列表中（如手动导入、已取关）时，取其最新一个已发布稿件上的信息。
- 登录后，只有未发布稿件的 UP 主也会返回（取其最新一个稿件上的信息），便于后台展示。
- 以上都不满足时返回 404。

---

## 管理接口：稿件

以下接口都需要登录。批量接口的请求体为 `{ "vids": ["BV1...", ...] }`，单次最多 500 个。

### `GET /api/admin/videos`

全部稿件列表，按发布时间倒序。

| 参数 | 说明 |
| --- | --- |
| `page` | 默认 1 |
| `size` | 默认 50，最大 200 |
| `filter` | `all`（默认）、`pending` 待下载/下载中、`local` 本地、`archived` 云盘、`download_failed` 下载失败、`upload_failed` 上传失败、`selected` 精选、`low_res` 分辨率不达标（包括重试中的和已被保留的） |
| `uid` | 可选，只看某个 UP 主 |
| `keyword` | 可选，匹配 vid（精确）、标题、BGM 标题、UP 主昵称 |

返回分页结构；传了 `keyword` 时额外返回 `ups`（匹配的 UP 主）。

### `POST /api/admin/videos/import`

手动导入稿件，导入后自动精选。

请求体：`{ "source": "bilibili" | "acfun", "vid": "BV1xx", "p": 1 }`，`p` 可省略。

返回 `{ "vid": "BV1xx[p2]" }`。已存在返回 409，解析失败返回 502。

### `POST /api/admin/videos/select`

精选或取消精选。请求体：`{ "vids": [...], "selected": true }`，`selected` 默认为 `true`。

返回 `{ "modified": 3 }`。

### `POST /api/admin/videos/retry-download`

重新下载：状态重置为待下载，并清零重试次数。不受自动下载的时长限制，会优先处理。正在下载中的稿件会被跳过。

已有的本地文件和云盘文件**不会预先删除**。新版本下载成功并替换本地文件后，云盘上的旧版本会在上传新版本之前删除；如果下载一直失败，稿件会回到原来的版本。重新下载期间，稿件的 `dstatus` 不再是 `200`/`201`，所以暂时不会出现在前台。

返回 `{ "queued": n }`。

### `POST /api/admin/videos/retry-upload`

对本地、尚未上传的稿件清零上传重试次数，让上传阶段重新拾取。返回 `{ "modified": n }`。

### `POST /api/admin/videos/reset-bgm`

把 BGM 识别状态重置为待识别。只对本地文件仍在（`dstatus = 200`）的稿件生效。返回 `{ "modified": n }`。

### `POST /api/admin/videos/delete`

删除稿件记录，以及本地和云盘上的视频、封面。返回 `{ "deleted": n }`。

### `POST /api/admin/videos/delete-range`

批量删除发布时间在区间内、**未精选**的稿件及文件。

请求体：`{ "start": 1700000000, "end": 1700086400, "uid": 123 }`，`start` 和 `end` 是秒级时间戳（闭区间），`uid` 可选。

返回 `{ "deleted": n }`。

### `PUT /api/admin/videos/<vid>/owner`

修改稿件归属的 UP 主。请求体：`{ "uid": 123, "uname": "..." }`。

### `PUT /api/admin/videos/<vid>/bgm-title`

修改 BGM 标题。请求体：`{ "title": "..." }`。

- 稿件已识别出 Shazam 曲目时，修改的是**曲目**标题，所有使用该曲目的稿件都会变化，返回 `{ "scope": "song" }`。
- 否则只修改该稿件的 `etitle`，返回 `{ "scope": "video" }`。

---

## 管理接口：后台任务

后台共有四个阶段，由 worker 进程按间隔调度，每次运行都是一个独立子进程。

| name | 名称 | 默认间隔 | 默认超时 |
| --- | --- | --- | --- |
| `fetch` | 获取动态 | 15 分钟 | 10 分钟 |
| `download` | 下载视频 | 2 分钟 | 60 分钟 |
| `upload` | 上传云盘 | 1 分钟 | 120 分钟 |
| `match` | 识别 BGM | 5 分钟 | 30 分钟 |

### `GET /api/admin/tasks`

```json
{
  "worker": { "online": true, "heartbeat_at": "2026-09-30T07:24:54+00:00" },
  "tasks": [
    {
      "name": "upload",
      "label": "上传云盘",
      "enabled": true,
      "paused_reason": null,
      "running": false,
      "run_requested": false,
      "last_started_at": "...",
      "last_finished_at": "...",
      "last_status": "ok",
      "last_summary": "上传成功 3 个，失败 0 个",
      "last_error": null,
      "last_error_item": null,
      "last_error_at": null,
      "consecutive_failures": 0,
      "interval_minutes": 1,
      "timeout_minutes": 120
    }
  ]
}
```

- `worker.online`：worker 每 10 秒写一次心跳，超过 60 秒没有心跳即视为离线。
- `last_status`：上一轮的结果，`ok` / `failed` / `timeout`，从未运行过为 `null`。
- `last_summary`：上一轮的处理摘要。
- `last_error` / `last_error_item` / `last_error_at`：最近一次错误及对应稿件（形如 `[BV1xx] 标题`）。成功的轮次不会清空它，便于事后排查。
- `paused_reason`：被自动暂停的原因。上传阶段连续多个稿件失败（默认 3 个，通常是云盘登录失效）时会自动关闭并写入这个字段。
- `consecutive_failures`：当前连续失败的稿件数。

### `PATCH /api/admin/tasks/<name>`

开启或关闭某个阶段。请求体：`{ "enabled": true }`。返回更新后的任务对象。

- 关闭后 worker 不再启动新一轮；正在运行的一轮会在处理完当前稿件后停止，不会中途打断。
- 开启时会同时清空 `paused_reason` 和 `consecutive_failures`。

### `POST /api/admin/tasks/<name>/run`

请求立即执行一轮，worker 会在 10 秒内开始。该阶段已关闭时返回 409；如果正在运行，这次请求会被忽略。

---

## 管理接口：B站 cookie

共有两类 cookie，`<kind>` 取值如下：

| kind | 用途 | 后台未配置时回退 |
| --- | --- | --- |
| `subscribe` | 读取关注分组和动态流 | 环境变量 `FO_COOKIE`（SESSDATA 值） |
| `download` | yt-dlp 下载视频，决定能拿到的最高画质 | 环境变量 `DL_COOKIE_FILE` 指向的 cookies.txt |

后台保存的值优先于环境变量。各阶段每轮开始时重新读取，保存后下一轮即生效，不需要重启。

下载阶段每轮开始前会检测下载 cookie。如果检测为未登录（包括没有配置），会自动暂停下载，`paused_reason` 以"下载 cookie 已失效"开头；之后保存或检测到有效的下载 cookie 时，下载会自动恢复。网络原因导致检测失败时不会暂停。获取动态阶段遇到未登录时，本轮失败，任务的 `last_error` 会提示更新订阅 cookie。

### Cookie 对象

接口不会返回 cookie 的值。

```json
{
  "kind": "download",
  "label": "下载 cookie",
  "configured": true,
  "source": "admin",
  "format": "netscape",
  "names": ["SESSDATA", "bili_jct", "buvid3"],
  "domains": [".bilibili.com"],
  "expires_at": "2027-03-01T00:00:00+00:00",
  "updated_at": "2026-09-30T08:00:00+00:00",
  "last_check": {
    "checked_at": "2026-09-30T08:00:01+00:00",
    "logged_in": true,
    "uid": 123,
    "uname": "xxx",
    "vip": true,
    "error": null
  },
  "error": null
}
```

- `source`：`admin` 表示后台配置，`env` 表示环境变量，未配置为 `null`。
- `format`：`sessdata`、`header`、`netscape`，含义见下方的保存接口。
- `expires_at`：SESSDATA 的过期时间，取自 cookies.txt 的过期列或 SESSDATA 值本身，无法得知时为 `null`。
- `last_check.logged_in`：`true` 已登录，`false` 未登录或已失效，`null` 表示检测时网络出错（原因见 `error`）。
- `error`：已保存的内容无法解析时的原因。

### `GET /api/admin/cookies`

返回 `{ "subscribe": Cookie, "download": Cookie }`。

### `PUT /api/admin/cookies/<kind>`

保存 cookie，保存后立即检测一次登录状态。请求体：`{ "content": "..." }`。`content` 支持以下三种格式，会自动识别：

- **单独的 SESSDATA 值**，如 `abc123%2C1767225600%2Cdef*b1`；
- **请求头格式**，如 `SESSDATA=...; bili_jct=...; buvid3=...`，可以直接从浏览器开发者工具中复制，开头的 `Cookie:` 可带可不带；
- **Netscape cookies.txt 文件内容**，即浏览器扩展导出的格式，可以包含 AcFun 等其他域名的 cookie。

内容中必须包含 bilibili.com 的 SESSDATA，否则返回 400。

返回 Cookie 对象，另外附带 `download_resumed`，表示下载是否因此自动恢复。`message` 会说明检测结果，例如"已保存，登录账号：xxx"或"已保存，但检测为未登录"。

### `DELETE /api/admin/cookies/<kind>`

清除后台配置，回退使用环境变量。返回 Cookie 对象。

### `POST /api/admin/cookies/<kind>/check`

重新检测登录状态，返回 Cookie 对象和 `download_resumed`。

---

## 管理接口：系统

### `GET /api/admin/checkpoint`

动态截止时间：`{ "timestamp": 1767225600, "datetime": "2026-01-01 08:00:00" }`。获取动态阶段只抓取这个时间之后发布的动态，每轮结束后自动推进。

### `PUT /api/admin/checkpoint`

手动设置截止时间。请求体二选一：

- `{ "datetime": "2026-01-01 08:00:00" }`，按 `TZ`（默认 Asia/Shanghai）解析；
- `{ "timestamp": 1767225600 }`。

不能晚于当前时间。

### `GET /api/admin/storage`

```json
{
  "local_bytes": 1234567890,
  "cloud": { "used_bytes": 1, "total_bytes": 2, "error": null }
}
```

云盘容量获取失败时，`used_bytes` 和 `total_bytes` 为 `null`，`error` 为失败原因。

### `GET /api/admin/stats`

```json
{
  "total": 1000,
  "by_dstatus": [{ "dstatus": 0, "label": "待下载", "count": 12 }],
  "selected": 300,
  "waiting_upload": 2,
  "waiting_match": 5
}
```

---

## 旧接口对照

| 旧接口 | 新接口 |
| --- | --- |
| `POST /api/admin.login` | `POST /api/auth/login`，字段 `pw` 改为 `password` |
| `POST /api/admin.logout` | `POST /api/auth/logout` |
| `GET /api/exp.list` | `GET /api/videos` |
| `GET /api/video.detail/<vid>` | `GET /api/videos/<vid>`，`more` 改为 `related`，`filesrc` 改为 `play_url` |
| `GET /api/fuzzy.search` | `GET /api/search` |
| `GET /api/up.info/<uid>` | `GET /api/ups/<uid>` |
| `GET /api/dyn.list` | `GET /api/admin/videos`，`dtype` 改为 `filter` |
| `POST /api/add.vid` | `POST /api/admin/videos/import`，`type` 改为 `source` |
| `POST /api/upload.ytb` | `POST /api/admin/videos/select` |
| `POST /api/retry` | `POST /api/admin/videos/retry-download`，请求体改为 `{ "vids": [...] }` |
| `POST /api/reset.bgm` | `POST /api/admin/videos/reset-bgm` |
| `POST /api/reset.upload` | 已移除（YouTube 上传的遗留接口）；云盘上传用 `retry-upload` |
| `POST /api/delete.video` | `POST /api/admin/videos/delete`，请求体改为 `{ "vids": [...] }` |
| `POST /api/delete.batch` | `POST /api/admin/videos/delete-range`，字段 `pd`/`ts` 改为 `start`/`end`，并且现在需要登录 |
| `POST /api/redirect.uid` | `PUT /api/admin/videos/<vid>/owner` |
| `POST /api/edit.title` | `PUT /api/admin/videos/<vid>/bgm-title` |
| `GET /api/init/<datestring>` | `PUT /api/admin/checkpoint` |
| `GET /api/folder.size` | `GET /api/admin/storage`（容量改为字节数）+ `GET /api/admin/tasks` |
| `GET /api/toggle.bgtask` | `PATCH /api/admin/tasks/upload` |
| `POST /api/find.local` | `GET /api/videos/<vid>` 中的 `play_url` |
