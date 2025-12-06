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
from pipelines.dental_age.dental_age_pipeline import DentalAgePipeline  # v4 新增

# Timer 配置初始化
from tools.timer import configure_from_config

logger = logging.getLogger(__name__)


_PIPELINE_CACHE: Dict[str, Any] = {}
_PIPELINE_SETTINGS: Dict[str, Dict[str, Any]] = {}
_PIPELINES_INITIALIZED = False
_PIPELINE_BUILDERS: Dict[str, Type] = {
    'panoramic': PanoPipeline,
    'cephalometric': CephPipeline,
    'dental_age_stage': DentalAgePipeline,  # v4 新增
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
    
    # 初始化 Timer 配置
    configure_from_config(config)
    
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
        try:
            pipeline = builder(**init_kwargs)
            _PIPELINE_CACHE[task_type] = pipeline
            # 检查是否处于mock模式
            if hasattr(pipeline, 'is_mock_mode') and pipeline.is_mock_mode:
                logger.warning(
                    "Pipeline %s initialized in MOCK MODE (model weights not available)",
                    task_type
                )
        except Exception as e:
            # Pipeline初始化失败（非权重加载失败），记录错误但不阻止Worker启动
            # 权重加载失败已在Pipeline内部处理，会设置mock模式
            logger.error(
                "Failed to preload pipeline %s: %s. "
                "It will be created on first use (may enter mock mode if weights unavailable).",
                task_type,
                e
            )
            # 不将失败的Pipeline加入缓存，让get_pipeline在首次使用时尝试创建

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
    try:
        pipeline = builder(**init_kwargs)
        _PIPELINE_CACHE[task_type] = pipeline
        # 检查是否处于mock模式
        if hasattr(pipeline, 'is_mock_mode') and pipeline.is_mock_mode:
            logger.warning(
                "Pipeline %s loaded in MOCK MODE (model weights not available)",
                task_type
            )
        return pipeline
    except Exception as e:
        # Pipeline初始化失败（非权重加载失败），抛出异常
        # 权重加载失败已在Pipeline内部处理，会设置mock模式，不会抛出异常
        logger.error(f"Failed to create pipeline {task_type}: {e}")
        raise


try:
    _preload_pipelines()
except Exception:
    logger.exception("Failed to preload pipelines during worker bootstrap")
    raise


@celery_app.task(name='server.tasks.analyze_task', bind=True)
def analyze_task(self, task_id: str, task_type: str, image_path: str, 
                 image_url: str = None, patient_info=None, pixel_spacing=None,
                 callback_url=None, metadata=None):
    """
    统一的推理任务（v4 架构：支持伪同步和纯异步）
    
    参数:
        self: Celery 任务实例（bind=True 时自动注入）
        task_id: 任务 ID
        task_type: 任务类型（panoramic/cephalometric/dental_age_stage）
        image_path: 图像文件路径
        image_url: 原始图像 URL（可选，纯异步回调时使用）
        patient_info: 患者信息（可选，侧位片必需）
        pixel_spacing: 像素间距/比例尺信息（可选，从 DICOM 或请求中获取）
        callback_url: 回调 URL（可选）
            - None：伪同步模式（直接返回结果）
            - 有值：纯异步模式（发送回调）
        metadata: 客户端元数据（可选）
    
    执行流程:
        1. 加载 Pipeline
        2. 执行推理
        3. 根据 callback_url 决定行为：
           - 如果为 None：返回结果（伪同步）
           - 如果有值：发送回调（纯异步）
    
    v4 架构特点:
        - 所有参数通过 Celery 传递，不依赖 Redis
        - 统一任务同时支持伪同步和纯异步
        - 伪同步时 P1 等待，不占用 GPU/CPU
    """
    logger.info(f"[Worker] Task started: {task_id}, type={task_type}, "
                f"mode={'pseudo-sync' if not callback_url else 'async'}")
    
    try:
        # 1. 获取 Pipeline
        pipeline = get_pipeline(task_type)
        
        # 2. 执行推理
        if task_type == 'panoramic':
            data_dict = pipeline.run(image_path=image_path, pixel_spacing=pixel_spacing)
        elif task_type == 'cephalometric':
            data_dict = pipeline.run(image_path=image_path, patient_info=patient_info, pixel_spacing=pixel_spacing)
        elif task_type == 'dental_age_stage':
            data_dict = pipeline.run(image_path=image_path)
        else:
            raise ValueError(f"Unknown task_type: {task_type}")
        
        logger.info(f"[Worker] Task completed: {task_id}")
        
        # 获取 is_mock 状态
        is_mock = getattr(pipeline, 'is_mock_mode', False)
        
        # 3. 根据 callback_url 决定行为
        if callback_url:
            # 纯异步：发送回调
            from server.core.callback import CallbackManager
            
            config = load_config()
            callback_mgr = CallbackManager(config)
            
            payload = {
                "taskId": task_id,
                "status": "SUCCESS",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata or {},
                "requestParameters": {
                    "taskType": task_type,
                    "imageUrl": image_url or ""  # v4：通过任务参数传递
                },
                "data": data_dict,
                "error": None,
                "is_mock": is_mock
            }
            
            success = callback_mgr.send_callback(callback_url, payload)
            logger.info(f"[Worker] Callback sent: {callback_url}, success={success}")
            return None  # 纯异步不返回结果
        else:
            # 伪同步：返回包含 data 和 is_mock 的字典
            return {
                "data": data_dict,
                "is_mock": is_mock
            }
    
    except Exception as e:
        logger.error(f"[Worker] Task failed: {task_id}, {e}", exc_info=True)
        
        # 如果是纯异步模式，发送错误回调
        if callback_url:
            try:
                from server.core.callback import CallbackManager
                
                config = load_config()
                callback_mgr = CallbackManager(config)
                
                payload = {
                    "taskId": task_id,
                    "status": "FAILURE",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "metadata": metadata or {},
                    "requestParameters": {"taskType": task_type},
                    "data": None,
                    "error": {
                        "code": 12001,
                        "message": f"AI model execution failed: {str(e)}",
                        "displayMessage": "AI 模型分析失败"
                    }
                }
                callback_mgr.send_callback(callback_url, payload)
            except Exception as cb_error:
                logger.error(f"[Worker] Failed to send error callback: {cb_error}")
        
        # 异常会被 Celery 捕获，P1 会收到 TaskError（伪同步模式）
        raise
