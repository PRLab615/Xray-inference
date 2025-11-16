# -*- coding: utf-8 -*-
"""
Celery 应用实例定义
配置任务队列系统
"""

from celery import Celery
from server import load_config
import logging

logger = logging.getLogger(__name__)


def create_celery_app() -> Celery:
    """
    创建 Celery 应用实例
    
    Returns:
        Celery: 配置完成的 Celery 应用对象
        
    工作流程：
    1. 加载配置文件
    2. 创建 Celery 实例（配置 broker 和 backend）
    3. 配置序列化格式和时区
    4. 自动发现任务模块
    """
    # 加载配置
    config = load_config()
    celery_config = config['celery']
    
    # 创建 Celery 实例
    celery_app = Celery(
        'xray_inference',
        broker=celery_config['broker_url'],
        backend=celery_config['result_backend']
    )
    
    # 配置 Celery
    celery_app.conf.update(
        task_serializer='json',
        result_serializer='json',
        accept_content=['json'],
        timezone='UTC',
        enable_utc=True,
        task_track_started=True,
        task_time_limit=3600,  # 1 小时超时
        worker_prefetch_multiplier=1,  # 每次只取一个任务
    )
    
    # 注意：不在这里 autodiscover_tasks，避免循环导入
    # 任务注册将在 main_worker.py 中通过显式导入 server.tasks 完成
    
    logger.info("Celery app created successfully")
    logger.info(f"Broker: {celery_config['broker_url']}")
    logger.info(f"Backend: {celery_config['result_backend']}")
    
    return celery_app


# 创建全局 Celery 实例
celery_app = create_celery_app()

