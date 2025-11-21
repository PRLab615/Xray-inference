# -*- coding: utf-8 -*-
"""
Worker 服务启动入口 (P2)
负责监听任务队列，执行 AI 计算，触发回调
"""

import logging
import os
from server.worker import celery_app
from server import load_config

# 显式导入任务模块以注册 Celery 任务（避免循环导入）
import server.tasks  # noqa: F401

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """
    启动 Celery Worker 服务
    
    工作流程:
        1. 加载配置文件
        2. 配置 Worker 参数（并发数、日志级别）
        3. 启动 Celery Worker 进程
        
    Note:
        - Windows 系统使用 solo pool（单进程模式）
        - Linux/Unix 系统使用 prefork pool（多进程模式）
        - Worker 会阻塞运行，直到手动停止
    """
    config = load_config()
    worker_config = config['worker']
    
    logger.info("=" * 60)
    logger.info("Starting Celery Worker Service")
    logger.info("=" * 60)
    logger.info(f"Concurrency: {worker_config['concurrency']}")
    logger.info(f"Log Level: {worker_config['loglevel']}")
    logger.info("=" * 60)
    
    # 构造 Worker 启动参数
    worker_args = [
        'worker',
        f'--loglevel={worker_config["loglevel"]}',
        f'--concurrency={worker_config["concurrency"]}',
    ]
    
    # Worker pool 配置
    # 注意：使用 threads 而非 prefork，因为 PyTorch/YOLO 不支持 fork()
    # 详见：docs/YOLO_FORK_ISSUE.md
    if os.name == 'nt':
        worker_args.append('--pool=solo')
        logger.info("Platform: Windows (using solo pool)")
    else:
        worker_args.append('--pool=threads')
        logger.info("Platform: Unix/Linux (using threads pool)")
    
    # 启动 Worker
    celery_app.worker_main(worker_args)


if __name__ == "__main__":
    main()
