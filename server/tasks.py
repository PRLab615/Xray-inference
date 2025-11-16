# -*- coding: utf-8 -*-
"""
AI 任务定义
根据 taskType 调用对应的 pipeline 执行推理
第一版实现：使用 mock_inference() 模拟推理结果
"""

import logging
import os
import time
from typing import Dict, Any
from server.worker import celery_app
from server.core.persistence import TaskPersistence
from server.core.callback import CallbackManager
from server import load_config

logger = logging.getLogger(__name__)


def mock_inference(task_type: str, image_path: str) -> Dict[str, Any]:
    """
    模拟 AI 推理（第一版实现）
    
    Args:
        task_type: 任务类型（pano/ceph）
        image_path: 图像文件路径（第一版未使用，预留给第二版）
        
    Returns:
        Dict: 模拟的推理结果数据
        
    Note:
        - 第一版返回固定的示例 JSON
        - 第二版将替换为真实的 pipeline 调用
        - 保持接口签名不变，便于后续演进
    """
    logger.info(f"Running mock inference: task_type={task_type}, image_path={image_path}")
    
    # 模拟耗时（2秒）
    time.sleep(2)
    
    if task_type == 'pano':
        # 全景片固定输出
        return {
            "teeth": [
                {"id": 11, "status": "healthy", "confidence": 0.95},
                {"id": 12, "status": "healthy", "confidence": 0.93},
                {"id": 21, "status": "caries", "confidence": 0.87},
                {"id": 22, "status": "healthy", "confidence": 0.91}
            ],
            "diseases": [
                {
                    "type": "caries",
                    "location": "tooth_21",
                    "severity": "mild",
                    "confidence": 0.87
                }
            ]
        }
    elif task_type == 'ceph':
        # 头影测量固定输出
        return {
            "landmarks": [
                {"name": "Sella", "x": 120.5, "y": 85.3, "confidence": 0.92},
                {"name": "Nasion", "x": 135.2, "y": 62.1, "confidence": 0.89},
                {"name": "A_Point", "x": 142.8, "y": 98.7, "confidence": 0.88}
            ],
            "measurements": {
                "SNA": 82.5,
                "SNB": 78.3,
                "ANB": 4.2
            }
        }
    else:
        # 未知类型返回空结果
        logger.warning(f"Unknown task_type: {task_type}")
        return {}


@celery_app.task(name='server.tasks.analyze_task', bind=True)
def analyze_task(self, task_id: str):
    """
    异步推理任务
    
    Args:
        self: Celery 任务实例（bind=True 时自动注入）
        task_id: 任务 ID
        
    工作流程:
        1. 从 Redis 获取任务元数据
        2. 检查图像文件是否存在
        3. 执行 Mock 推理（第一版）或真实推理（第二版）
        4. 构造回调负载（成功或失败）
        5. 发送 HTTP 回调
        6. 清理 Redis 元数据（回调成功时）
        
    Note:
        - 遵循 fail-fast 原则，不捕获异常（让 Celery 处理重试）
        - 图像文件不存在或推理失败时，发送错误回调
        - 回调失败不删除元数据，便于后续手动重试
    """
    logger.info(f"Task started: {task_id}")
    
    # 加载配置和初始化组件
    config = load_config()
    persistence = TaskPersistence(config)
    callback_mgr = CallbackManager(config)
    
    # 1. 获取任务元数据
    metadata = persistence.get_task(task_id)
    if not metadata:
        logger.error(f"Task not found in Redis: {task_id}")
        return
    
    task_type = metadata['taskType']
    image_path = metadata['imagePath']
    callback_url = metadata['callbackUrl']
    
    logger.info(f"Task metadata retrieved: task_type={task_type}, image_path={image_path}")
    
    # 2. 检查图像文件是否存在
    if not os.path.exists(image_path):
        logger.error(f"Image file not found: {image_path}")
        payload = {
            "taskId": task_id,
            "data": None,
            "error": {
                "code": 12002,
                "message": "Image file not found"
            }
        }
        callback_mgr.send_callback(callback_url, payload)
        persistence.delete_task(task_id)
        return
    
    # 3. 执行推理
    payload = None
    inference_result = mock_inference(task_type, image_path)
    logger.info(f"Inference completed: {task_id}")
    
    # 4. 构造成功回调负载
    payload = {
        "taskId": task_id,
        "data": inference_result,
        "error": None
    }
    
    # 5. 发送回调
    success = callback_mgr.send_callback(callback_url, payload)
    
    # 6. 清理任务元数据（仅当回调成功时）
    if success:
        persistence.delete_task(task_id)
        logger.info(f"Task completed and cleaned: {task_id}")
    else:
        logger.warning(f"Task completed but callback failed, metadata retained: {task_id}")
