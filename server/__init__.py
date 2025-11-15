"""
服务层模块
负责 API, 队列, 回调等服务功能
"""

import yaml
import os
from pathlib import Path
from typing import Any, Dict


def load_config() -> Dict[str, Any]:
    """
    加载配置文件，支持环境变量覆盖
    
    环境变量优先级高于配置文件：
    - REDIS_HOST: Redis 主机地址
    - REDIS_PORT: Redis 端口
    - REDIS_DB: Redis 数据库索引
    - REDIS_PASSWORD: Redis 密码
    
    Returns:
        Dict[str, Any]: 配置字典
        
    Raises:
        FileNotFoundError: 配置文件不存在
        yaml.YAMLError: YAML 解析失败
    """
    config_path = Path(__file__).parent.parent / "config.yaml"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    if not config:
        raise ValueError("Configuration file is empty")
    
    # 环境变量覆盖 Redis 配置
    if 'REDIS_HOST' in os.environ:
        config['redis']['host'] = os.environ['REDIS_HOST']
    if 'REDIS_PORT' in os.environ:
        config['redis']['port'] = int(os.environ['REDIS_PORT'])
    if 'REDIS_DB' in os.environ:
        config['redis']['db'] = int(os.environ['REDIS_DB'])
    if 'REDIS_PASSWORD' in os.environ:
        config['redis']['password'] = os.environ['REDIS_PASSWORD']
    
    # 动态更新 Celery 配置中的 Redis 地址
    redis_host = config['redis']['host']
    redis_port = config['redis']['port']
    redis_password = config['redis'].get('password')
    
    if redis_password:
        redis_url = f"redis://:{redis_password}@{redis_host}:{redis_port}"
    else:
        redis_url = f"redis://{redis_host}:{redis_port}"
    
    config['celery']['broker_url'] = f"{redis_url}/0"
    config['celery']['result_backend'] = f"{redis_url}/1"
    
    return config

