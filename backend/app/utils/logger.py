import logging
import os
import sys

_FILENAME = "news.log"


def setup_logging(enable_file: bool = False, level: int = logging.INFO) -> logging.Logger:
    """统一日志配置：控制台 +（可选）滚动文件。返回根 logger。"""
    root = logging.getLogger()
    if root.handlers:
        return root

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    root.setLevel(level)

    if enable_file:
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(os.path.join(log_dir, _FILENAME), encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    return root


def get_logger(name: str = "news") -> logging.Logger:
    return logging.getLogger(name)
