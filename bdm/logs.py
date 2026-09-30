import logging

from bdm import config


def setup_logging():
    logging.basicConfig(
        format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=config.LOG_LEVEL.upper(),
    )
    logging.getLogger('apscheduler').setLevel(logging.WARNING)
