# -*- coding: utf-8 -*-
"""
API 路由定义
负责处理 HTTP 请求，实现 202/400 逻辑
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
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


# ==================== 自定义异常处理器（统一错误响应格式）====================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    处理 Pydantic 参数验证错误，统一返回接口定义的错误格式
    
    将 Pydantic 的 422 错误格式转换为：
    {
        "code": 10001,
        "message": "Invalid parameter: ...",
        "displayMessage": "请求参数错误"
    }
    """
    # 提取错误信息
    errors = exc.errors()
    error_messages = []
    for error in errors:
        loc = ".".join(str(x) for x in error.get("loc", []))
        msg = error.get("msg", "Unknown error")
        error_messages.append(f"{loc}: {msg}")
    
    detail_message = "; ".join(error_messages)
    
    return JSONResponse(
        status_code=400,  # 使用 400 而非 422，与接口定义一致
        content={
            "code": 10001,
            "message": f"Invalid parameter: {detail_message}",
            "displayMessage": "请求参数错误"
        }
    )


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
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message=f"Invalid parameter 'taskId': {task_id} is already in use",
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
                code=11004,
                message=f"Cannot download image from '{request.imageUrl}'",
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
                code=12002,
                message="AI model execution timed out",
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
                code=12001,
                message="AI model execution failed",
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
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message=f"Invalid parameter 'taskId': {request.taskId} is already in use",
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
                code=11004,
                message=f"Cannot download image from '{request.imageUrl}'",
                detail=str(e)
            ).model_dump()
        )
    except Exception as e:
        logger.error(f"Image download failed: {e}")
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=11004,
                message=f"Cannot download image from '{request.imageUrl}'",
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
                code=50001,
                message="Internal server error",
                detail="Failed to save task metadata to Redis"
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
                code=50003,
                message="Task queue service unavailable",
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
    全景片重算接口（v4 新增）
    
    功能：
        接收客户端修改后的基础几何数据（分割掩码、检测框、分类结果），
        跳过模型推理，重新计算所有衍生数据（对称性判断、缺牙推导、描述文本等），
        返回完整的全景片报告。
    
    技术细节:
        - 在 P1 中实现（不在 P2）
        - 使用 def 而非 async def，因为报告生成是同步 CPU 密集型任务
        - FastAPI 会自动在线程池中运行，不会阻塞事件循环
    
    Args:
        request: 重算请求（对齐接口定义）
            - taskId: 任务唯一标识，仅用于日志追踪
            - data: 完整的全景片推理结果 JSON（即 example_pano_result.json 格式）
    
    Returns:
        RecalculateResponse: 包含重算后的完整报告（格式与推理接口一致）
        
    Raises:
        HTTPException(400): 参数验证失败
        HTTPException(500): 报告生成失败
    
    工作流程（当前实现）:
        1. 验证请求参数
        2. 暂时直接返回 data（不做处理）
        3. 后续实现：提取"因"字段，重新计算"果"字段
    
    注意:
        - 当前暂时直接返回，因为需要所有推理模块的后处理写完才能集成
        - 输入是推理的格式，输出返回的也是推理的格式，所以直接返回就是正确的格式
    """
    logger.info(f"[Pano Recalculate] Request received: taskId={request.taskId}")
    
    try:
        # 1. 校验 taskId（schema 已校验 UUID 格式，这里再次确认）
        if not request.taskId:
            raise ValueError("taskId is required")
        
        # 2. 校验 data 不为空
        if not request.data:
            raise ValueError("data is required and cannot be empty")
        
        # TODO: 后续实现重算逻辑
        # 3. 从 request.data 中提取"因"字段（基础几何数据）
        # 4. 重新计算"果"字段（对称性判断、缺牙推导、描述文本等）
        # 5. 返回完整的全景片报告
        
        # 当前实现：直接返回 data（因为输入输出格式一致）
        logger.info(f"[Pano Recalculate] Directly returning data (recalculation logic to be implemented): taskId={request.taskId}")
        
        return RecalculateResponse(
            taskId=request.taskId,
            status="SUCCESS",
            timestamp=datetime.now(timezone.utc).isoformat(),
            metadata=None,  # 接口定义中 metadata 可选
            data=request.data,  # 直接返回，格式与推理接口一致
            error=None
        )
    
    except ValueError as e:
        # 参数验证错误，返回 400
        logger.warning(f"[Pano Recalculate] Validation failed: {e}")
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message=f"Invalid parameter: {e}",
                detail=str(e)
            ).model_dump()
        )
    except Exception as e:
        logger.error(f"[Pano Recalculate] Failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                code=12001,
                message="AI model execution failed",
                detail=str(e)
            ).model_dump()
        )


@app.post("/api/v1/measurements/ceph/recalculate", status_code=200)
def recalculate_ceph_measurements(request: CephRecalculateRequest) -> RecalculateResponse:
    """
    侧位片重算接口（v4 新增）
    
    功能：
        接收客户端修改后的完整推理结果（关键点坐标 + 颈椎分割），
        重新计算所有测量值，生成完整的侧位片报告。
    
    技术细节:
        - 在 P1 中实现（不在 P2）
        - 使用 def 而非 async def，因为测量计算和报告生成是同步 CPU 密集型任务
        - FastAPI 会自动在线程池中运行，不会阻塞事件循环
    
    Args:
        request: 重算请求（对齐接口定义）
            - taskId: 任务唯一标识，仅用于日志追踪
            - data: 完整的侧位片推理结果 JSON（即 example_ceph_result.json 格式）
    
    Returns:
        RecalculateResponse: 包含重算后的完整报告（格式与推理接口一致）
        
    Raises:
        HTTPException(400): 参数验证失败
        HTTPException(500): 报告生成失败
    
    工作流程（当前实现）:
        1. 验证请求参数
        2. 暂时直接返回 data（不做处理）
        3. 后续实现：提取"因"字段，重新计算"果"字段
    
    注意:
        - 当前暂时直接返回，因为需要所有推理模块的后处理写完才能集成
        - 输入是推理的格式，输出返回的也是推理的格式，所以直接返回就是正确的格式
    """
    logger.info(f"[Ceph Recalculate] Request received: taskId={request.taskId}")
    
    try:
        # 1. 校验 taskId（schema 已校验 UUID 格式，这里再次确认）
        if not request.taskId:
            raise ValueError("taskId is required")
        
        # 2. 校验 data 不为空
        if not request.data:
            raise ValueError("data is required and cannot be empty")
        
        # 3. 校验 patientInfo（侧位片必填，schema 已校验，这里再次确认）
        if not request.patientInfo:
            raise ValueError("patientInfo is required for cephalometric recalculation")
        
        # 4. 校验 Gender（schema 已校验，这里再次确认）
        gender = request.patientInfo.gender
        if gender not in ["Male", "Female"]:
            raise ValueError(f"patientInfo.gender must be 'Male' or 'Female', got '{gender}'")
        
        # 5. 校验 DentalAgeStage（schema 已校验，这里再次确认）
        dental_age_stage = request.patientInfo.DentalAgeStage
        if dental_age_stage not in ["Permanent", "Mixed"]:
            raise ValueError(f"patientInfo.DentalAgeStage must be 'Permanent' or 'Mixed', got '{dental_age_stage}'")
        
        logger.info(f"[Ceph Recalculate] Validation passed: taskId={request.taskId}, gender={gender}, dentalAgeStage={dental_age_stage}")
        
        # TODO: 后续实现重算逻辑
        # 6. 从 request.data 中提取"因"字段（关键点坐标、颈椎分割等）
        # 7. 重新计算"果"字段（所有测量值、测量值Level等）
        # 8. 返回完整的侧位片报告
        
        # 当前实现：直接返回 data（因为输入输出格式一致）
        logger.info(f"[Ceph Recalculate] Directly returning data (recalculation logic to be implemented): taskId={request.taskId}")
        
        return RecalculateResponse(
            taskId=request.taskId,
            status="SUCCESS",
            timestamp=datetime.now(timezone.utc).isoformat(),
            metadata=None,  # 接口定义中 metadata 可选
            data=request.data,  # 直接返回，格式与推理接口一致
            error=None
        )
    
    except ValueError as e:
        # 参数验证错误，返回 400
        logger.warning(f"[Ceph Recalculate] Validation failed: {e}")
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message=f"Invalid parameter: {e}",
                detail=str(e)
            ).model_dump()
        )
    except Exception as e:
        logger.error(f"[Ceph Recalculate] Failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                code=12001,
                message="AI model execution failed",
                detail=str(e)
            ).model_dump()
        )
