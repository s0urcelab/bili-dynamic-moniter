import logging
import asyncio
import subprocess
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from pymongo import MongoClient
from update import update
from match import shazam_match
from download import download
from constant import *

# 配置logger
formatter = '%(asctime)s %(levelname)s %(message)s'
logging.basicConfig(format=formatter, datefmt='%Y-%m-%d %H:%M:%S', level=logging.INFO)
logger = logging.getLogger('bdm')

async def main():
    client = MongoClient(MONGODB_URL)
    
    update(client)
    download(client)
    await shazam_match(client)
    
    client.close()
    
# 新增一个异步的启动入口
async def run_scheduler():
    scheduler = AsyncIOScheduler(timezone='Asia/Shanghai')
    scheduler.add_job(main, 'interval', minutes=15)
    
    def self_restart(event):
        subprocess.run(["docker", "restart", "bdm-downloader"])
        
    scheduler.add_listener(self_restart, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    
    # 此时事件循环正在运行，可以安全地启动调度器
    scheduler.start()
    
    # 阻塞该协程以保持事件循环持续运转
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(run_scheduler())