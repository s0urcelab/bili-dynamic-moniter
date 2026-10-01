import logging

from bdm import config


def setup_logging():
    logging.basicConfig(
        format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=config.LOG_LEVEL.upper(),
    )
    logging.getLogger('apscheduler').setLevel(logging.WARNING)
    # shazamio 的 Rust 核心会先用 MP3 解码器探测 mp4，失败后才交给 ffmpeg，每个文件刷数百行无害警告
    logging.getLogger('symphonia_core').setLevel(logging.ERROR)
    logging.getLogger('symphonia_bundle_mp3').setLevel(logging.ERROR)
