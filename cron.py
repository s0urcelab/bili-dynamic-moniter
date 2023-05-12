
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from update import update
from match import match
from download import download

if __name__ == '__main__':
    scheduler = AsyncIOScheduler(timezone='Asia/Shanghai')
    scheduler.add_job(update, 'interval', minutes=10)
    scheduler.add_job(match, 'interval', minutes=10)
    scheduler.add_job(download, 'interval', minutes=15)
    scheduler.start()
    asyncio.get_event_loop().run_forever()