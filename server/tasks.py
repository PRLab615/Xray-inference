# -*- coding: utf-8 -*-
"""
AI 任务定义
根据 taskType 调用对应的 pipeline 执行推理
第一版实现：使用 mock_inference() 模拟推理结果
v2: 从 example JSON 文件加载完整数据，支持新的回调格式
"""

import logging
import os
import time
import json
from pathlib import Path
from typing import Dict, Any
from datetime import datetime, timezone
from server.worker import celery_app
from server.core.persistence import TaskPersistence
from server.core.callback import CallbackManager
from server import load_config

logger = logging.getLogger(__name__)


def load_mock_data(task_type: str) -> Dict[str, Any]:
    """
    从 example JSON 文件加载 mock 数据的 data 字段（v2）
    
    Args:
        task_type: 任务类型（panoramic/cephalometric）
        
    Returns:
        Dict: data 字段的完整 JSON
        
    Note:
        - 从 server/example_pano_result.json 或 server/example_ceph_result.json 加载
        - 提取 JSON 文件中的 'data' 字段
        - 如果文件不存在或解析失败，返回空字典
    """
    logger.info(f"Loading mock data for task_type: {task_type}")
    
    # 确定文件路径
    if task_type == 'panoramic':
        example_file = Path(__file__).parent / 'example_pano_result.json'
    elif task_type == 'cephalometric':
        example_file = Path(__file__).parent / 'example_ceph_result.json'
    else:
        logger.warning(f"Unknown task type for mock data: {task_type}")
        return {}
    
    # 检查文件是否存在
    if not example_file.exists():
        logger.error(f"Example file not found: {example_file}")
        return {}
    
    # 读取并解析 JSON
    try:
        with open(example_file, 'r', encoding='utf-8') as f:
            full_json = json.load(f)
            data_field = full_json.get('data', {})
            logger.info(f"Mock data loaded successfully: {len(data_field)} top-level keys")
            return data_field
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from {example_file}: {e}")
        return {}
    except Exception as e:
        logger.error(f"Failed to load mock data from {example_file}: {e}")
        return {}


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
    异步推理任务（v2 协议）
    
    Args:
        self: Celery 任务实例（bind=True 时自动注入）
        task_id: 任务 ID
        
    工作流程:
        1. 从 Redis 获取任务元数据（v2 扩展字段）
        2. 检查图像文件是否存在
        3. 加载 Mock 数据（从 example JSON）
        4. 构造回调负载 v2（包含 status, timestamp, metadata, requestParameters）
        5. 发送 HTTP 回调
        6. 清理 Redis 元数据（回调成功时）
        
    Note:
        - v2 新增：从 metadata_v2 中获取 metadata, imageUrl, patientInfo
        - v2 新增：回调 payload 包含完整的 v2 字段
        - v2 暂不实现错误回调（延后到 v3）
    """
    logger.info(f"Task started: {task_id}")
    
    # 加载配置和初始化组件
    config = load_config()
    persistence = TaskPersistence(config)
    callback_mgr = CallbackManager(config)
    
    # 1. 获取任务元数据 v2
    metadata_v2 = persistence.get_task(task_id)
    if not metadata_v2:
        logger.error(f"Task not found in Redis: {task_id}")
        return
    
    task_type = metadata_v2['taskType']
    image_path = metadata_v2['imagePath']
    callback_url = metadata_v2['callbackUrl']
    client_metadata = metadata_v2.get('metadata', {})
    image_url = metadata_v2.get('imageUrl', '')
    patient_info = metadata_v2.get('patientInfo')
    
    logger.info(f"Task metadata retrieved: task_type={task_type}, image_path={image_path}")
    
    # 2. 检查图像文件是否存在
    if not os.path.exists(image_path):
        # v2 暂不实现错误回调
        logger.error(f"Image file not found: {image_path}")
        return
    
    # 3. 加载 Mock 数据（从 example JSON）
    try:
        data_dict = load_mock_data(task_type)
        logger.info(f"Mock data loaded for {task_type}: {task_id}")
    
        # 4. 构造 CallbackPayload v2
        payload_v2 = {
        "taskId": task_id,
            "status": "SUCCESS",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": client_metadata,
            "requestParameters": {
                "taskType": task_type,
                "imageUrl": image_url
            },
            "data": data_dict,
        "error": None
    }
    
    except Exception as e:
        # v2 暂不实现错误回调
        logger.error(f"Failed to load mock data: {task_id}, {e}")
        return
    
    # 5. 发送回调 v2
    success = callback_mgr.send_callback(callback_url, payload_v2)
    
    # 6. 清理任务元数据（仅当回调成功时）
    if success:
        persistence.delete_task(task_id)
        logger.info(f"Task completed and cleaned: {task_id}")
    else:
        logger.warning(f"Task completed but callback failed, metadata retained: {task_id}")
