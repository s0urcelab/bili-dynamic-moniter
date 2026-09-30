import importlib

# 阶段实现按需导入，避免调度进程和 API 进程加载 yt-dlp、shazamio 等重依赖
_ENTRYPOINTS = {
    'fetch': 'bdm.tasks.fetch',
    'download': 'bdm.tasks.download',
    'upload': 'bdm.tasks.upload',
    'match': 'bdm.tasks.match',
}


def load(name):
    return importlib.import_module(_ENTRYPOINTS[name]).run
