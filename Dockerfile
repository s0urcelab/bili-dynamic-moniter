FROM python:3.9.16-slim-bullseye

# 修改时区
ENV TZ=Asia/Shanghai

WORKDIR /app
COPY . /app

# 安装项目依赖
RUN pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --no-cache-dir

RUN apt-get update && apt-get install -y cron && apt-get install -y ffmpeg

# 创建定时任务
RUN crontab /app/crontab

# 执行定时任务
# CMD ["cron","-f", "-l", "2"]
# 运行flask
CMD ["gunicorn", "main:app", "-c", "./gunicorn.conf.py"]

EXPOSE 7002

