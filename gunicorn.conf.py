import os

wsgi_app = 'wsgi:app'
bind = os.environ.get('API_BIND', '0.0.0.0:7002')
# 后台任务已全部移到 worker，API 进程无状态，可以按需增加 worker 数
workers = int(os.environ.get('API_WORKERS', 2))
worker_class = 'gevent'
timeout = 60
accesslog = '-'
errorlog = '-'
# 兜底：即使有泄漏，每个 worker 处理一定请求后也会被平滑替换
max_requests = 2000
max_requests_jitter = 200
