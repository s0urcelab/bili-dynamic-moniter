FROM python:3.11-slim-bookworm

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MALLOC_ARENA_MAX=2

# ffmpeg：yt-dlp 合并音视频、ffprobe 校验分辨率、shazamio 解码 mp4 音频
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 7002

# 默认启动 API；worker 使用同一镜像，命令为 python -m bdm.worker
CMD ["gunicorn", "-c", "gunicorn.conf.py"]
