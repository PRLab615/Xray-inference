# -*- coding: utf-8 -*-
"""
AI 任务定义
根据 taskType 调用对应的 pipeline 执行推理
v3: 使用真实 Pipeline，移除 mock 数据
"""

import logging
import os
from datetime import datetime, timezone
from server.worker import celery_app
from server.core.persistence import TaskPersistence
from server.core.callback import CallbackManager
from server import load_config

# v3 新增：导入 Pipeline
from pipelines.pano.pano_pipeline import PanoPipeline
from pipelines.ceph.ceph_pipeline import CephPipeline

logger = logging.getLogger(__name__)


@celery_app.task(name='server.tasks.analyze_task', bind=True)
def analyze_task(self, task_id: str):
    """
    异步推理任务（v3 协议：真实 Pipeline）
    
    Args:
        self: Celery 任务实例（bind=True 时自动注入）
        task_id: 任务 ID
        
    工作流程:
        1. 从 Redis 获取任务元数据（v2 扩展字段）
        2. 检查图像文件是否存在
        3. 根据 taskType 实例化对应的 Pipeline（v3 新增）
        4. 调用 pipeline.run() 获取真实推理结果（v3 新增）
        5. 构造回调负载 v3（data 来自 Pipeline）
        6. 发送 HTTP 回调
        7. 清理 Redis 元数据（回调成功时）
        
    变更点（v2 → v3）:
        - ❌ 移除 load_mock_data() 调用
        - ✅ 新增 Pipeline 实例化和调用
        - ✅ 传递 patient_info 给 CephPipeline
    """
    logger.info(f"Task started: {task_id}")
    
    # 加载配置和初始化组件
    config = load_config()
    persistence = TaskPersistence(config)
    callback_mgr = CallbackManager(config)
    
    try:
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
            # v3 暂不实现错误回调（延后到 v4）
            logger.error(f"Image file not found: {image_path}")
            return
        
        # 3. 根据 taskType 实例化 Pipeline 并执行推理（v3 新增）
        try:
            if task_type == 'panoramic':
                # 全景片推理
                logger.info(f"Instantiating PanoPipeline for {task_id}")
                pipeline = PanoPipeline()
                data_dict = pipeline.run(image_path=image_path)
                
            elif task_type == 'cephalometric':
                # 侧位片推理（需要 patient_info）
                logger.info(f"Instantiating CephPipeline for {task_id}")
                pipeline = CephPipeline()
                data_dict = pipeline.run(image_path=image_path, patient_info=patient_info)
                
            else:
                logger.error(f"Unknown task_type: {task_type}")
                return
            
            logger.info(f"Pipeline execution completed for {task_id}")
        
        except Exception as e:
            # v3 暂不实现错误回调（延后到 v4）
            logger.error(f"Pipeline execution failed: {task_id}, {e}", exc_info=True)
            return
        
        # 4. 构造 CallbackPayload v3（data 来自 Pipeline）
        payload_v3 = {
            "taskId": task_id,
            "status": "SUCCESS",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": client_metadata,
            "requestParameters": {
                "taskType": task_type,
                "imageUrl": image_url
            },
            "data": data_dict,  # v3: 来自 Pipeline 真实推理
            "error": None
        }
        
        # 5. 发送回调 v3
        success = callback_mgr.send_callback(callback_url, payload_v3)
        
        # 6. 清理任务元数据（仅当回调成功时）
        if success:
            persistence.delete_task(task_id)
            logger.info(f"Task completed and cleaned: {task_id}")
        else:
            logger.warning(f"Task completed but callback failed, metadata retained: {task_id}")
    
    except Exception as e:
        logger.error(f"Task execution failed: {task_id}, {e}", exc_info=True)
