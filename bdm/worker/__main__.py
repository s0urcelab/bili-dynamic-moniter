"""
Worker 调度进程：python -m bdm.worker

只负责按间隔触发各阶段，每次触发都起一个子进程执行，自身不加载任何业务依赖。
"""
import logging
import os
import signal
import subprocess
import sys
from datetime import datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler

from bdm import config, db
from bdm.logs import setup_logging
from bdm.tasks import state

logger = logging.getLogger('bdm.worker')

POLL_SECONDS = 10

_running = {}


def _kill_tree(proc):
    try:
        if hasattr(os, 'killpg'):
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except ProcessLookupError:
        pass
    proc.wait()


def run_stage(name):
    if not state.is_enabled(name):
        logger.debug('[%s] 已关闭，跳过', name)
        return

    timeout = config.SCHEDULE[name]['timeout'] * 60
    state.mark_started(name)
    status, error = 'ok', None
    try:
        # 独立进程组，超时时连同 yt-dlp 拉起的 ffmpeg 一起结束
        proc = subprocess.Popen([sys.executable, '-m', 'bdm.worker.run', name], start_new_session=True)
        _running[name] = proc
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            status, error = 'timeout', f'执行超过 {timeout // 60} 分钟，已强制终止'
        else:
            if code != 0:
                status, error = 'failed', f'子进程退出码 {code}'
    except Exception as err:
        status, error = 'failed', f'{type(err).__name__}: {err}'
        logger.exception('[%s] 启动失败', name)
    finally:
        _running.pop(name, None)
        state.mark_finished(name, status, error)

    if status != 'ok':
        logger.error('[%s] %s', name, error)


def poll(scheduler):
    """心跳 + 处理 API 发来的立即执行请求。"""
    try:
        state.heartbeat()
        for name in state.pop_run_requests():
            job = scheduler.get_job(name)
            if job:
                logger.info('[%s] 收到立即执行请求', name)
                job.modify(next_run_time=datetime.now(config.TZ))
    except Exception:
        logger.exception('轮询任务状态失败')


def main():
    setup_logging()
    db.init()
    state.ensure_all()
    state.reset_running()

    scheduler = BlockingScheduler(timezone=config.TZ)
    start = datetime.now(config.TZ)
    for i, name in enumerate(state.STAGES):
        scheduler.add_job(
            run_stage, 'interval', args=[name], id=name, name=name,
            minutes=config.SCHEDULE[name]['interval'],
            next_run_time=start + timedelta(seconds=5 * i),
            max_instances=1, coalesce=True, misfire_grace_time=None,
        )
        logger.info('已注册阶段 %s：每 %d 分钟，超时 %d 分钟',
                    name, config.SCHEDULE[name]['interval'], config.SCHEDULE[name]['timeout'])
    scheduler.add_job(poll, 'interval', args=[scheduler], id='_poll', seconds=POLL_SECONDS,
                      max_instances=1, coalesce=True)

    def shutdown(signum, frame):
        logger.info('收到退出信号，停止调度')
        scheduler.shutdown(wait=False)
        for proc in list(_running.values()):
            _kill_tree(proc)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    scheduler.start()


if __name__ == '__main__':
    main()
