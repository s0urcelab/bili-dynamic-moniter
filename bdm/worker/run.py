"""
执行单个阶段后退出：python -m bdm.worker.run <stage>

每次运行都是独立进程，第三方库残留的内存会随进程退出全部回收。
"""
import logging
import sys

from bdm import tasks
from bdm.logs import setup_logging
from bdm.tasks import state

logger = logging.getLogger('bdm.worker')


def main(argv):
    if len(argv) != 2 or argv[1] not in state.STAGES:
        print(f'用法：python -m bdm.worker.run <{"|".join(state.STAGES)}>', file=sys.stderr)
        return 2

    name = argv[1]
    setup_logging()
    try:
        summary = tasks.load(name)()
    except Exception as err:
        logger.exception('阶段 %s 执行失败', name)
        state.report_error(name, f'{type(err).__name__}: {err}')
        return 1

    logger.info('[%s] %s', state.STAGE_LABELS[name], summary)
    state.report_summary(name, summary)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
