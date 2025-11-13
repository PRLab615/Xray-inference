"""
服务层模块
负责 API, 队列, 回调等服务功能
"""

import yaml
from pathlib import Path
from typing import Any, Dict


def load_config() -> Dict[str, Any]:
    """
    加载配置文件
    
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
    
    return config

