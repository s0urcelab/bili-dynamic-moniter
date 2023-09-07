import logging
import asyncio
import subprocess
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from pymongo import MongoClient
from update import update
from match import shazam_match
from download import download

# 配置logger
formatter = '%(asctime)s %(levelname)s %(message)s'
logging.basicConfig(format=formatter, datefmt='%Y-%m-%d %H:%M:%S', level=logging.INFO)
logger = logging.getLogger('bdm')

async def main():
    client = MongoClient("mongodb://host.docker.internal:27017/")
    
    update(client)
    download(client)
    await shazam_match(client)
    
    client.close()

if __name__ == '__main__':
    scheduler = AsyncIOScheduler(timezone='Asia/Shanghai')
    scheduler.add_job(main, 'interval', minutes=15)
    def self_restart(event):
        subprocess.run(["docker", "restart", "bdm-downloader"])
    scheduler.add_listener(self_restart, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    scheduler.start()
    asyncio.get_event_loop().run_forever()