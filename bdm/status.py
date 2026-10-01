"""
稿件的状态字段。数值与历史数据保持一致，不要修改已有取值。

下载流水线（dstatus）：
    PENDING ──download──> DOWNLOADING ──> LOCAL ──upload + match 均完成──> CLOUD
                                  └──失败──> 负数错误码（可重试的会被 download 再次拾取）

重新下载时新版本先落在临时目录，只有比本地已有版本更好（或达标）才替换；
失败时已有的本地文件不动，重试用尽后退回使用已有版本。

BGM 识别（shazam_id）：0 待识别，正数为 Shazam 曲目 id，负数为失败原因。
"""


class DStatus:
    PENDING = 0
    DOWNLOADING = 100
    LOCAL = 200     # 本地文件已就绪，等待上传/识别
    CLOUD = 201     # 已上传云盘且识别完成，本地文件已清理

    FAILED = -1         # yt-dlp 或其他未知错误
    FILE_MISSING = -2   # 下载完成但找不到文件
    LOW_RES = -3        # 分辨率不达标（本地保留目前最好的版本，等待重试）
    DETAIL_FAILED = -9  # 获取稿件详情失败（不重试）
    PAID = -11          # 充电专属（不重试）

    NON_RETRYABLE = (DETAIL_FAILED, PAID)


class UStatus:
    DEFAULT = 0
    SELECTED = 100  # 精选
    UPLOADED = 200  # 历史遗留（YouTube 上传），按精选处理


class ShazamStatus:
    PENDING = 0
    NO_MATCH = -1
    NO_FILE = -2
    ERROR = -3


class Source:
    """稿件来源，影响本地文件命名规则。字符串（hash）表示本地手动下载。"""
    BILIX = 0
    IMPORT_BILI = 1
    DYNAMIC = 2
    IMPORT_ACFUN = 3


DSTATUS_LABELS = {
    DStatus.PENDING: '待下载',
    DStatus.DOWNLOADING: '下载中',
    DStatus.LOCAL: '本地',
    DStatus.CLOUD: '云盘',
    DStatus.FAILED: '下载失败',
    DStatus.FILE_MISSING: '文件缺失',
    DStatus.LOW_RES: '分辨率不达标',
    DStatus.DETAIL_FAILED: '获取详情失败',
    DStatus.PAID: '充电专属',
}
