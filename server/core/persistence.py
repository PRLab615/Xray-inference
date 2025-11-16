# -*- coding: utf-8 -*-
"""
任务状态持久化
负责 Redis 读/写操作
"""

import redis
import json
import logging
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


class TaskPersistence:
    """
    任务元数据持久化管理
    
    负责将任务元数据保存到 Redis，支持增删查操作。
    所有操作遵循 fail-fast 原则，连接错误直接抛出异常。
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化 Redis 连接
        
        Args:
            config: 配置字典，需包含 redis 和 task 配置项
            
        Raises:
            redis.ConnectionError: Redis 连接失败
            KeyError: 配置项缺失
        """
        redis_config = config['redis']
        self.redis_client = redis.Redis(
            host=redis_config['host'],
            port=redis_config['port'],
            db=redis_config['db'],
            password=redis_config.get('password'),
            decode_responses=True
        )
        self.key_prefix = "task:"
        self.ttl = config['task']['result_ttl']
        
        # 测试连接
        self.redis_client.ping()
        logger.info(f"Redis connected: {redis_config['host']}:{redis_config['port']}/{redis_config['db']}")
    
    def _build_key(self, task_id: str) -> str:
        """
        构建 Redis key
        
        Args:
            task_id: 任务 ID
            
        Returns:
            str: Redis key (格式: task:{task_id})
        """
        return f"{self.key_prefix}{task_id}"
    
    def save_task(self, task_id: str, metadata: Dict[str, Any]) -> bool:
        """
        保存任务元数据到 Redis
        
        Args:
            task_id: 任务 ID
            metadata: 任务元数据字典
            
        Returns:
            bool: 保存是否成功
            
        Raises:
            redis.RedisError: Redis 操作失败
        """
        key = self._build_key(task_id)
        value = json.dumps(metadata, ensure_ascii=False)
        
        result = self.redis_client.setex(key, self.ttl, value)
        
        if result:
            logger.info(f"Task saved: {task_id}, TTL={self.ttl}s")
            return True
        else:
            logger.error(f"Failed to save task: {task_id}")
            return False
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务元数据
        
        Args:
            task_id: 任务 ID
            
        Returns:
            Optional[Dict]: 任务元数据字典，不存在时返回 None
            
        Raises:
            redis.RedisError: Redis 操作失败
            json.JSONDecodeError: JSON 解析失败
        """
        key = self._build_key(task_id)
        value = self.redis_client.get(key)
        
        if value is None:
            logger.warning(f"Task not found: {task_id}")
            return None
        
        metadata = json.loads(value)
        logger.debug(f"Task retrieved: {task_id}")
        return metadata
    
    def task_exists(self, task_id: str) -> bool:
        """
        检查任务是否存在
        
        Args:
            task_id: 任务 ID
            
        Returns:
            bool: 任务是否存在
            
        Raises:
            redis.RedisError: Redis 操作失败
        """
        key = self._build_key(task_id)
        exists = self.redis_client.exists(key) > 0
        logger.debug(f"Task exists check: {task_id} -> {exists}")
        return exists
    
    def delete_task(self, task_id: str) -> bool:
        """
        删除任务元数据
        
        Args:
            task_id: 任务 ID
            
        Returns:
            bool: 删除是否成功（删除数量 > 0）
            
        Raises:
            redis.RedisError: Redis 操作失败
        """
        key = self._build_key(task_id)
        deleted_count = self.redis_client.delete(key)
        
        if deleted_count > 0:
            logger.info(f"Task deleted: {task_id}")
            return True
        else:
            logger.warning(f"Task not found for deletion: {task_id}")
            return False
