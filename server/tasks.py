# -*- coding: utf-8 -*-
"""
AI 任务定义
根据 taskType 调用对应的 pipeline 执行推理
v3: 使用真实 Pipeline，移除 mock 数据
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Type

from server.worker import celery_app
from server.core.persistence import TaskPersistence
from server.core.callback import CallbackManager
from server import load_config

# v3 新增：导入 Pipeline
from pipelines.pano.pano_pipeline import PanoPipeline
from pipelines.ceph.ceph_pipeline import CephPipeline

logger = logging.getLogger(__name__)


_PIPELINE_CACHE: Dict[str, Any] = {}
_PIPELINE_SETTINGS: Dict[str, Dict[str, Any]] = {}
_PIPELINES_INITIALIZED = False
_PIPELINE_BUILDERS: Dict[str, Type] = {
    'panoramic': PanoPipeline,
    'cephalometric': CephPipeline,
}


def _extract_init_kwargs(settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    从配置中提取 Pipeline 初始化参数
    
    新架构（v3.2）：
        - 直接传递 modules 配置给 Pipeline
        - Pipeline 负责初始化所有 enabled 的模块
        - 不再使用 default_module 或 init_kwargs
    """
    if not isinstance(settings, dict):
        return {}
    
    modules = settings.get('modules')
    if isinstance(modules, dict):
        # 直接传递完整的 modules 配置
        return {'modules': modules}
    
    # 兼容旧配置：空配置
    return {}


def _preload_pipelines() -> None:
    global _PIPELINE_SETTINGS, _PIPELINES_INITIALIZED
    if _PIPELINES_INITIALIZED:
        return

    config = load_config()
    pipeline_config = config.get('pipelines', {})
    _PIPELINE_SETTINGS = pipeline_config

    for task_type, builder in _PIPELINE_BUILDERS.items():
        settings = pipeline_config.get(task_type, {})
        should_preload = settings.get('preload', True) if isinstance(settings, dict) else True
        init_kwargs = _extract_init_kwargs(settings)

        if not should_preload:
            logger.warning(
                "Pipeline preload disabled for %s. It will be created on first use.",
                task_type
            )
            continue

        logger.info("Preloading %s pipeline with kwargs=%s", task_type, init_kwargs)
        _PIPELINE_CACHE[task_type] = builder(**init_kwargs)

    _PIPELINES_INITIALIZED = True


def get_pipeline(task_type: str):
    pipeline = _PIPELINE_CACHE.get(task_type)
    if pipeline:
        return pipeline

    builder = _PIPELINE_BUILDERS.get(task_type)
    if not builder:
        raise ValueError(f"Unknown task_type: {task_type}")

    settings = _PIPELINE_SETTINGS.get(task_type, {})
    init_kwargs = _extract_init_kwargs(settings)
    logger.info(
        "Lazy-loading %s pipeline (preload disabled) with kwargs=%s",
        task_type,
        init_kwargs
    )
    pipeline = builder(**init_kwargs)
    _PIPELINE_CACHE[task_type] = pipeline
    return pipeline


try:
    _preload_pipelines()
except Exception:
    logger.exception("Failed to preload pipelines during worker bootstrap")
    raise


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
            pipeline = get_pipeline(task_type)

            if task_type == 'panoramic':
                # 全景片推理
                logger.info(f"Running PanoPipeline for {task_id}")
                data_dict = pipeline.run(image_path=image_path)

            elif task_type == 'cephalometric':
                # 侧位片推理（需要 patient_info）
                logger.info(f"Running CephPipeline for {task_id}")
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
        
        # 调试：打印 CephalometricMeasurements 的 Level 值
        if task_type == 'cephalometric' and 'CephalometricMeasurements' in data_dict:
            measurements = data_dict['CephalometricMeasurements'].get('AllMeasurements', [])
            logger.info(f"[调试] Pipeline 返回的 Level 值 (taskId={task_id}):")
            for m in measurements:
                label = m.get('Label', 'N/A')
                level = m.get('Level', 'N/A')
                level_type = type(level).__name__
                if 'Angle' in m:
                    value = m.get('Angle')
                    logger.info(f"  {label}: Level={level} (type={level_type}), Angle={value}")
                elif 'Ratio' in m:
                    value = m.get('Ratio')
                    logger.info(f"  {label}: Level={level} (type={level_type}), Ratio={value}")
            
            # 检查 JSON 序列化后的数据
            import json
            try:
                serialized = json.dumps(data_dict['CephalometricMeasurements'], ensure_ascii=False)
                logger.info(f"[调试] JSON 序列化测试: 成功，长度={len(serialized)}")
                # 反序列化检查
                deserialized = json.loads(serialized)
                logger.info(f"[调试] JSON 反序列化后的 Level 值:")
                for m in deserialized.get('AllMeasurements', []):
                    label = m.get('Label', 'N/A')
                    level = m.get('Level', 'N/A')
                    level_type = type(level).__name__
                    logger.info(f"  {label}: Level={level} (type={level_type})")
            except Exception as e:
                logger.error(f"[调试] JSON 序列化测试失败: {e}")
        
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
