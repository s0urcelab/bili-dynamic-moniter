# 定义同时开启的处理请求的进程数量，根据网站流量适当调整
workers = 2
# 采用gevent库，支持异步处理请求，提高吞吐量
worker_class = "gevent"
# 防止多个worker多次执行定时任务
# preload_app = True

# 绑定IP/端口
bind = "0.0.0.0:7002"