# -*- coding: utf-8 -*-
"""
API 路由定义
负责处理 HTTP 请求，实现 202/400 逻辑
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from server import load_config
from server.schemas import (
    AnalyzeRequest, 
    AnalyzeResponse, 
    SyncAnalyzeRequest, 
    SyncAnalyzeResponse,
    PanoRecalculateRequest,
    CephRecalculateRequest,
    RecalculateResponse,
    ErrorResponse,
    ErrorDetail
)
from datetime import datetime, timezone
import logging
import os
import time
import uuid

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """
    创建 FastAPI 应用实例
    
    Returns:
        FastAPI: 配置完成的 FastAPI 应用对象
    """
    app = FastAPI(
        title="X-Ray Inference Service",
        description="异步 AI 推理服务",
        version="1.0.0"
    )
    
    # 配置 CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 加载配置
    app.state.config = load_config()
    logger.info("FastAPI app created successfully")
    
    return app


# 创建应用实例
app = create_app()


@app.get("/")
async def root():
    """
    根路径
    
    Returns:
        dict: 服务基本信息
    """
    return {
        "service": "X-Ray Inference Service",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """
    健康检查接口
    
    Returns:
        dict: 健康状态
    """
    return {
        "status": "healthy",
        "service": "api"
    }


@app.get("/api/v1/health")
async def api_health_check():
    """
    API 健康检查接口
    
    Returns:
        dict: 健康状态
    """
    return {
        "status": "healthy",
        "service": "api"
    }


# ==================== 全局变量初始化 ====================
# 在应用启动时初始化，避免每次请求重复创建
_persistence = None
_image_downloader = None
_upload_dir = None


@app.on_event("startup")
async def startup_event():
    """
    应用启动事件（v4 伪同步架构）
    
    初始化全局单例:
        - TaskPersistence: Redis 持久化客户端（纯异步接口使用）
        - ImageDownloader: 图像下载器（从 URL 下载）
        - upload_dir: 图像存储目录路径
    
    注：v4 中移除了 InferenceService，所有推理都在 P2 (Worker) 中执行
    """
    global _persistence, _image_downloader, _upload_dir
    
    from server.core.persistence import TaskPersistence
    from server.utils.image_downloader import ImageDownloader
    
    config = app.state.config
    _persistence = TaskPersistence(config)
    _image_downloader = ImageDownloader(config)
    _upload_dir = config['api']['upload_dir']
    
    logger.info(f"API service initialized (v4 pseudo-sync architecture), image_dir: {_upload_dir}")


# ==================== 核心 API 接口 ====================

@app.post("/api/v1/analyze", status_code=200)
async def analyze(request: SyncAnalyzeRequest) -> SyncAnalyzeResponse:
    """
    伪同步推理接口（v4 架构）
    
    工作流程:
        1. 下载图像
        2. 提交任务到 Celery 队列（P2 执行推理）
        3. P1 等待结果（使用 run_in_executor 避免阻塞事件循环）
        4. 返回完整结果
    
    优势:
        - 客户端体验：同步（一次请求，一次响应）
        - 服务端架构：保留 P1/P2 分离
        - 资源隔离：推理在 P2 执行，不阻塞 P1
        - 协程挂起：使用 run_in_executor 包装阻塞调用，不阻塞事件循环
    
    技术细节:
        - celery_result.get() 是阻塞调用，不能直接在 async def 中使用
        - 使用 asyncio.get_event_loop().run_in_executor() 将其转为 awaitable
        - 这样等待时不会阻塞事件循环，P1 可以处理其他请求
    
    Args:
        request: 同步分析请求（JSON body，Pydantic 自动验证）
            - taskType: 任务类型（panoramic/cephalometric）
            - imageUrl: 图像 URL（HTTP/HTTPS）
            - taskId: 任务 ID（可选，服务端自动生成）
            - metadata: 客户端自定义元数据（可选）
            - patientInfo: 患者信息（cephalometric 必需）
        
    Returns:
        SyncAnalyzeResponse: 包含 taskId, status, timestamp, data/error 的响应
        
    Raises:
        HTTPException(400): 参数验证失败、图像下载失败
        HTTPException(504): 推理超时
        HTTPException(500): 服务器内部错误
    """
    from server.tasks import analyze_task
    import celery.exceptions
    import asyncio
    
    # 1. 检查 taskId 是否已存在（推理任务中 taskId 必须唯一）
    task_id = request.taskId
    if _persistence.task_exists(task_id):
        logger.warning(f"Task already exists: {task_id}")
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                code=10002,
                message="Task ID already exists",
                detail=f"taskId {task_id} is already in use"
            ).model_dump()
        )
    
    # 在 Redis 中设置临时标记，表示任务正在处理（防止并发重复提交）
    # 同步接口不持久化结果，但需要标记 taskId 已被使用
    try:
        _persistence.save_task(task_id, {
            "taskId": task_id,
            "taskType": request.taskType,
            "status": "PROCESSING",
            "mode": "sync"
        })
    except Exception as e:
        logger.error(f"Failed to mark task as processing: {task_id}, {e}")
        # 如果 Redis 操作失败，仍然继续处理，但记录警告
    
    logger.info(f"[Pseudo-Sync] Request received: taskId={task_id}, taskType={request.taskType}")
    
    # 2. 下载图像
    file_ext = '.jpg'
    image_filename = f"{task_id}{file_ext}"
    image_path = os.path.join(_upload_dir, image_filename)
    
    try:
        _image_downloader.download_image(request.imageUrl, image_path)
        logger.info(f"Image downloaded: {image_path}")
    except Exception as e:
        logger.error(f"Image download failed: {e}")
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10004,
                message="Image download failed",
                detail=str(e)
            ).model_dump()
        )
    
    # 3. 构造任务参数（伪同步：callback_url=None）
    task_params = {
        "task_id": task_id,
        "task_type": request.taskType,
        "image_path": image_path,
        "patient_info": request.patientInfo.model_dump() if request.patientInfo else None,
        "callback_url": None,  # 伪同步：不需要回调
        "metadata": request.metadata or {},
    }
    
    # 4. 提交到 Celery 队列
    logger.info(f"[Pseudo-Sync] Submitting task to Celery: {task_id}")
    celery_result = analyze_task.apply_async(kwargs=task_params)
    
    # 5. 【关键】等待 P2 完成（伪同步，使用 run_in_executor 避免阻塞事件循环）
    try:
        # 设置超时（可配置，默认 30 秒）
        timeout = 30  # 可从 config.yaml 读取
        logger.info(f"[Pseudo-Sync] Waiting for result (timeout={timeout}s): {task_id}")
        
        # 使用 run_in_executor 将阻塞的 get() 转为 awaitable
        # 这样等待时不会阻塞事件循环，P1 可以处理其他请求
        loop = asyncio.get_event_loop()
        data_dict = await loop.run_in_executor(
            None,  # 使用默认的 ThreadPoolExecutor
            lambda: celery_result.get(timeout=timeout)
        )
        
        logger.info(f"[Pseudo-Sync] Task completed: {task_id}")
        
        # 6. 清理临时文件
        if os.path.exists(image_path):
            os.remove(image_path)
            logger.info(f"Cleaned up temp file: {image_path}")
        
        # 7. 清理 Redis 中的临时标记（同步接口不持久化结果）
        try:
            _persistence.delete_task(task_id)
        except Exception as e:
            logger.warning(f"Failed to clean up task marker: {task_id}, {e}")
        
        # 8. 返回结果
        return SyncAnalyzeResponse(
            taskId=task_id,
            status="SUCCESS",
            timestamp=datetime.now(timezone.utc).isoformat(),
            metadata=request.metadata,
            data=data_dict,
            error=None
        )
    
    except celery.exceptions.TimeoutError:
        logger.error(f"[Pseudo-Sync] Task timeout: {task_id}")
        # 清理临时文件
        if os.path.exists(image_path):
            os.remove(image_path)
        # 清理 Redis 中的临时标记
        try:
            _persistence.delete_task(task_id)
        except Exception as e:
            logger.warning(f"Failed to clean up task marker: {task_id}, {e}")
        raise HTTPException(
            status_code=504,
            detail=ErrorResponse(
                code=50401,
                message="Inference timeout",
                detail=f"Task execution exceeded {timeout} seconds"
            ).model_dump()
        )
    
    except Exception as e:
        logger.error(f"[Pseudo-Sync] Task execution failed: {task_id}, {e}", exc_info=True)
        # 清理临时文件
        if os.path.exists(image_path):
            os.remove(image_path)
        # 清理 Redis 中的临时标记
        try:
            _persistence.delete_task(task_id)
        except Exception as e2:
            logger.warning(f"Failed to clean up task marker: {task_id}, {e2}")
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                code=10006,
                message="Inference failed",
                detail=str(e)
            ).model_dump()
        )


@app.post("/api/v1/analyze_async", status_code=202)
def analyze_async(request: AnalyzeRequest) -> AnalyzeResponse:
    """
    异步推理接口（通过回调返回结果）
    
    技术细节:
        - 使用 def 而非 async def，因为内部的 I/O 操作（图像下载、Redis）都是同步阻塞的
        - FastAPI 会自动在线程池中运行，不会阻塞事件循环
    
    Args:
        request: 分析请求（JSON body，Pydantic 自动验证）
            - taskId: 任务唯一标识（UUID v4 格式）
            - taskType: 任务类型（panoramic/cephalometric）
            - imageUrl: 图像 URL（HTTP/HTTPS）
            - callbackUrl: 回调 URL（HTTP/HTTPS）
            - metadata: 客户端自定义元数据（可选）
            - patientInfo: 患者信息（cephalometric 必需）
        
    Returns:
        AnalyzeResponse: 包含 taskId, status, submittedAt, metadata 的响应
        
    Raises:
        HTTPException(400): 参数验证失败、图像下载失败
        HTTPException(409): taskId 已存在
        HTTPException(500): 服务器内部错误（Redis/Celery）
        
    工作流程:
        1. Pydantic 自动验证请求参数（taskId、taskType、imageUrl 等）
        2. 检查 taskId 是否已存在（防止重复提交）
        3. 从 imageUrl 下载图像文件
        4. 保存任务元数据到 Redis
        5. 将任务推入 Celery 队列
        6. 返回 202 Accepted 响应
    """
    # 延迟导入 analyze_task 避免循环导入
    from server.tasks import analyze_task
    
    logger.info(f"Received async request: taskId={request.taskId}, taskType={request.taskType}, imageUrl={request.imageUrl}")
    
    # 1. 检查 taskId 是否已存在
    if _persistence.task_exists(request.taskId):
        logger.warning(f"Task already exists: {request.taskId}")
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                code=10002,
                message="Task ID already exists",
                detail=f"taskId {request.taskId} is already in use"
            ).model_dump()
        )
    
    # 2. 下载图像
    file_ext = '.jpg'
    image_filename = f"{request.taskId}{file_ext}"
    image_path = os.path.join(_upload_dir, image_filename)
    
    try:
        _image_downloader.download_image(request.imageUrl, image_path)
        logger.info(f"Image downloaded: {request.imageUrl} -> {image_path}")
    except ValueError as e:
        logger.error(f"Image validation failed: {e}")
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10004,
                message="Image validation failed",
                detail=str(e)
            ).model_dump()
        )
    except Exception as e:
        logger.error(f"Image download failed: {e}")
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10004,
                message="Image download failed",
                detail=str(e)
            ).model_dump()
        )
    
    # 3. 构造任务元数据
    submitted_at = time.time()
    metadata_v3 = {
        "taskId": request.taskId,
        "taskType": request.taskType,
        "imageUrl": request.imageUrl,
        "imagePath": image_path,
        "callbackUrl": request.callbackUrl,
        "metadata": request.metadata or {},
        "patientInfo": request.patientInfo.model_dump() if request.patientInfo else None,
        "submittedAt": submitted_at,
        "imageSource": "url"
    }
    
    # 4. 保存到 Redis
    success = _persistence.save_task(request.taskId, metadata_v3)
    if not success:
        # 清理已下载的图像
        if os.path.exists(image_path):
            os.remove(image_path)
            logger.info(f"Cleaned up image file: {image_path}")
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                code=10001,
                message="Failed to save task metadata",
                detail="Redis operation failed"
            ).model_dump()
        )
    
    # 5. 异步任务入队（v4：使用统一任务参数，所有信息通过 Celery 传递）
    try:
        task_params = {
            "task_id": request.taskId,
            "task_type": request.taskType,
            "image_path": image_path,
            "image_url": request.imageUrl,  # v4 新增：通过任务参数传递，不依赖 Redis
            "patient_info": request.patientInfo.model_dump() if request.patientInfo else None,
            "callback_url": request.callbackUrl,  # 纯异步：需要回调
            "metadata": request.metadata or {},
        }
        task_result = analyze_task.apply_async(kwargs=task_params)
        logger.info(f"Task queued: {request.taskId}, celery_id={task_result.id}")
    except Exception as e:
        # 回滚：删除 Redis 记录和图像文件
        _persistence.delete_task(request.taskId)
        if os.path.exists(image_path):
            os.remove(image_path)
            logger.info(f"Cleaned up image file: {image_path}")
        logger.error(f"Failed to queue task: {e}")
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                code=10001,
                message="Failed to queue task",
                detail=str(e)
            ).model_dump()
        )
    
    # 6. 返回 202 响应
    return AnalyzeResponse(
        taskId=request.taskId,
        status="QUEUED",
        submittedAt=datetime.fromtimestamp(submitted_at, tz=timezone.utc).isoformat(),
        metadata=request.metadata
    )


# ==================== 重算接口（v4 新增）====================

@app.post("/api/v1/measurements/pano/recalculate", status_code=200)
def recalculate_pano_measurements(request: PanoRecalculateRequest) -> RecalculateResponse:
    """
    全景片点位重算接口（v4 新增）
    
    功能：
        接收客户端修改后的检测结果（牙齿、髁突、种植体等），
        跳过模型推理，直接调用报告生成函数，返回完整的全景片报告。
    
    技术细节:
        - 使用 def 而非 async def，因为报告生成是同步 CPU 密集型任务
        - FastAPI 会自动在线程池中运行，不会阻塞事件循环
    
    Args:
        request: 重算请求
            - inferenceResults: 修改后的推理结果
            - metadata: 图像元信息（可选）
    
    Returns:
        RecalculateResponse: 包含重算后的完整报告
        
    Raises:
        HTTPException(400): 参数验证失败
        HTTPException(500): 报告生成失败
    
    工作流程:
        1. 验证请求参数
        2. 调用 pano_report_utils.generate_standard_output()
        3. 返回完整报告
    """
    from pipelines.pano.utils.pano_report_utils import generate_standard_output
    
    logger.info(f"[Pano Recalculate] Request received: taskId={request.taskId}")
    
    try:
        # 构造 metadata（使用客户端提供的或默认值）
        metadata = request.metadata or {
            "source": "manual_edit",
            "timestamp": time.time()
        }
        
        # 调用报告生成函数
        report = generate_standard_output(
            metadata=metadata,
            inference_results=request.inferenceResults
        )
        
        logger.info(f"[Pano Recalculate] Report generated successfully: taskId={request.taskId}")
        
        # 返回结果
        return RecalculateResponse(
            taskId=request.taskId,
            status="SUCCESS",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=report,
            error=None
        )
    
    except Exception as e:
        logger.error(f"[Pano Recalculate] Failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                code=10007,
                message="Pano recalculation failed",
                detail=str(e)
            ).model_dump()
        )


@app.post("/api/v1/measurements/ceph/recalculate", status_code=200)
def recalculate_ceph_measurements(request: CephRecalculateRequest) -> RecalculateResponse:
    """
    侧位片点位重算接口（v4 新增）
    
    功能：
        接收客户端修改后的关键点坐标，
        重新计算测量值，生成完整的侧位片报告。
    
    技术细节:
        - 使用 def 而非 async def，因为测量计算和报告生成是同步 CPU 密集型任务
        - FastAPI 会自动在线程池中运行，不会阻塞事件循环
    
    Args:
        request: 重算请求
            - landmarks: 修改后的关键点坐标
            - patientInfo: 患者信息
            - imageSpacing: 图像间距（可选）
    
    Returns:
        RecalculateResponse: 包含重算后的完整报告
        
    Raises:
        HTTPException(400): 参数验证失败
        HTTPException(500): 报告生成失败
    
    工作流程:
        1. 验证请求参数
        2. 转换坐标格式（dict -> numpy.ndarray）
        3. 调用 calculate_measurements() 计算测量值
        4. 调用 generate_standard_output() 生成报告
        5. 返回完整报告
    """
    from pipelines.ceph.utils.ceph_report import calculate_measurements
    from pipelines.ceph.utils.ceph_report_json import generate_standard_output
    import numpy as np
    
    logger.info(f"[Ceph Recalculate] Request received: taskId={request.taskId}")
    
    try:
        # 1. 转换坐标格式（dict -> numpy.ndarray）
        landmarks = {
            label: np.array([coord['x'], coord['y']]) 
            for label, coord in request.landmarks.items()
        }
        
        logger.info(f"[Ceph Recalculate] Converted {len(landmarks)} landmarks: taskId={request.taskId}")
        
        # 2. 计算测量值
        measurements = calculate_measurements(landmarks)
        
        logger.info(f"[Ceph Recalculate] Calculated measurements: taskId={request.taskId}")
        
        # 3. 构造 inference_results
        inference_results = {
            "landmarks": {
                "coordinates": landmarks,
                "confidences": {k: 1.0 for k in landmarks.keys()}  # 手动编辑视为高置信度
            },
            "measurements": measurements
        }
        
        # 4. 生成报告
        report = generate_standard_output(
            inference_results=inference_results,
            patient_info=request.patientInfo.model_dump()
        )
        
        logger.info(f"[Ceph Recalculate] Report generated successfully: taskId={request.taskId}")
        
        # 返回结果
        return RecalculateResponse(
            taskId=request.taskId,
            status="SUCCESS",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=report,
            error=None
        )
    
    except Exception as e:
        logger.error(f"[Ceph Recalculate] Failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                code=10008,
                message="Ceph recalculation failed",
                detail=str(e)
            ).model_dump()
        )
