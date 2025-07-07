# file: utils/logger.py

import sys
from loguru import logger

# 默认情况下，只输出到控制台
logger.remove()
logger.add(sys.stderr, level="INFO")

def setup_llm_logger(log_file_path: str = None):
    """
    Configures a specific logger for LLM requests.
    
    Args:
        log_file_path: Path to the file where LLM requests will be logged.
                       If None, logging to file is disabled.
    """
    # 给 LLM 请求日志一个专门的名称，以便于过滤和管理
    # 我们可以在这里配置日志格式、轮转等
    if log_file_path:
        try:
            # format 参数定义了日志的格式
            # rotation 和 retention 控制日志文件轮转
            logger.add(
                log_file_path, 
                level="DEBUG", 
                format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
                rotation="1000 MB", # 每个文件最大1000MB
                retention="7 days", # 保留7天的日志
                enqueue=True, # 异步写入，不阻塞主线程
                backtrace=True,
                diagnose=True,
                # 使用 filter 来确保只有特定的日志被写入这个文件
                filter=lambda record: "llm_request" in record["extra"]
            )
            print(f"LLM request logging is enabled. Logs will be saved to: {log_file_path}")
        except Exception as e:
            print(f"Failed to set up LLM request logger at {log_file_path}: {e}")

# 在模块加载时，可以不设置文件日志，等待配置
# setup_llm_logger()