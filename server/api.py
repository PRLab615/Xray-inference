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

def _wait_for_celery_result_polling(celery_result, timeout, poll_interval=0.2):
    """
    使用轮询方式等待 Celery 结果（替代 pub/sub）
    
    Celery 的 AsyncResult.get() 默认使用 Redis pub/sub，在高并发下
    多个线程同时调用会导致连接冲突（I/O operation on closed file）。
    
    此函数使用轮询 ready()/successful() 来检查任务状态，
    这些方法使用简单的 Redis GET 操作，更加可靠。
    
    Args:
        celery_result: Celery AsyncResult 对象
        timeout: 超时时间（秒）
        poll_interval: 轮询间隔（秒），默认 0.2s
    
    Returns:
        任务结果
        
    Raises:
        celery.exceptions.TimeoutError: 超时
        Exception: 任务执行失败时抛出原始异常
    """
    import celery.exceptions
    
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        if celery_result.ready():
            # 任务完成（成功或失败）
            if celery_result.successful():
                return celery_result.result
            else:
                # 任务失败，获取并抛出异常
                # 注意：这里 get() 只是获取已完成的结果，不会阻塞
                celery_result.get(propagate=True)
        time.sleep(poll_interval)
    
    # 超时
    raise celery.exceptions.TimeoutError(f"Task did not complete within {timeout} seconds")


@app.post("/api/v1/analyze", status_code=200)
async def analyze(request: SyncAnalyzeRequest) -> SyncAnalyzeResponse:
    """
    伪同步推理接口（v4 架构）
    
    工作流程:
        1. 下载图像（支持 imageUrl 或 dicomUrl）
        2. 如果是 DICOM，转换为 JPG 并提取患者信息和比例尺
        3. 提交任务到 Celery 队列（P2 执行推理）
        4. P1 等待结果（使用 run_in_executor 避免阻塞事件循环）
        5. 返回完整结果
    
    优势:
        - 客户端体验：同步（一次请求，一次响应）
        - 服务端架构：保留 P1/P2 分离
        - 资源隔离：推理在 P2 执行，不阻塞 P1
        - 协程挂起：使用 run_in_executor 包装阻塞调用，不阻塞事件循环
    
    技术细节:
        - 使用轮询方式（而非 pub/sub）等待 Celery 结果
        - 轮询更可靠，避免高并发下 Redis 连接冲突
        - 使用 asyncio.get_event_loop().run_in_executor() 将其转为 awaitable
        - 这样等待时不会阻塞事件循环，P1 可以处理其他请求
    
    Args:
        request: 同步分析请求（JSON body，Pydantic 自动验证）
            - taskType: 任务类型（panoramic/cephalometric）
            - imageUrl: 图像 URL（HTTP/HTTPS），与 dicomUrl 二选一
            - dicomUrl: DICOM 文件 URL（HTTP/HTTPS），与 imageUrl 二选一
            - taskId: 任务 ID（必填）
            - metadata: 客户端自定义元数据（可选）
            - patientInfo: 患者信息（cephalometric 必需，但 dicomUrl 模式可从 DICOM 解析）
            - pixelSpacing: 比例尺信息（可选，用于非 DICOM 图像）
        
    Returns:
        SyncAnalyzeResponse: 包含 taskId, status, timestamp, data/error 的响应
        
    Raises:
        HTTPException(400): 参数验证失败、图像下载失败
        HTTPException(504): 推理超时
        HTTPException(500): 服务器内部错误
    """
    from server.tasks import analyze_task
    from tools.dicom_utils import extract_dicom_info_for_inference
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
    try:
        _persistence.save_task(task_id, {
            "taskId": task_id,
            "taskType": request.taskType,
            "status": "PROCESSING",
            "mode": "sync"
        })
    except Exception as e:
        logger.error(f"Failed to mark task as processing: {task_id}, {e}")
    
    logger.info(f"[Pseudo-Sync] Request received: taskId={task_id}, taskType={request.taskType}")
    
    # 2. 下载图像（支持 imageUrl 或 dicomUrl）
    image_path = None
    dicom_path = None
    patient_info = request.patientInfo.model_dump() if request.patientInfo else None
    pixel_spacing = None
    temp_files = []  # 记录需要清理的临时文件
    
    try:
        if request.dicomUrl:
            # DICOM 模式：下载 DICOM -> 转换 JPG -> 提取患者信息和比例尺
            dicom_filename = f"{task_id}.dcm"
            dicom_path = os.path.join(_upload_dir, dicom_filename)
            temp_files.append(dicom_path)
            
            _image_downloader.download_dicom(request.dicomUrl, dicom_path)
            logger.info(f"DICOM downloaded: {dicom_path}")
            
            # 转换 DICOM 并提取信息
            dicom_info = extract_dicom_info_for_inference(dicom_path, out_dir=_upload_dir)
            image_path = dicom_info["image_path"]
            temp_files.append(image_path)
            
            # 从 DICOM 提取患者信息（如果请求中没有提供）
            if not patient_info and dicom_info["patient_info"]["gender"]:
                patient_info = dicom_info["patient_info"]
                logger.info(f"Patient info extracted from DICOM: {patient_info}")
            
            # 从 DICOM 提取比例尺
            if dicom_info["pixel_spacing"]["available"]:
                pixel_spacing = {
                    "scale_x": dicom_info["pixel_spacing"]["scale_x"],
                    "scale_y": dicom_info["pixel_spacing"]["scale_y"],
                    "source": "dicom",
                }
                logger.info(f"Pixel spacing extracted from DICOM: {pixel_spacing}")
        else:
            # 普通图像模式
            file_ext = '.jpg'
            image_filename = f"{task_id}{file_ext}"
            image_path = os.path.join(_upload_dir, image_filename)
            temp_files.append(image_path)
            
            _image_downloader.download_image(request.imageUrl, image_path)
            logger.info(f"Image downloaded: {image_path}")
            
            # 使用请求中的比例尺
            if request.pixelSpacing:
                pixel_spacing = {
                    "scale_x": request.pixelSpacing.scaleX,
                    "scale_y": request.pixelSpacing.scaleY or request.pixelSpacing.scaleX,
                    "source": "request",
                }
                logger.info(f"Pixel spacing from request: {pixel_spacing}")
    except Exception as e:
        logger.error(f"Image/DICOM download failed: {e}")
        # 清理临时文件
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=11004,
                message=f"Cannot download image/DICOM from '{request.dicomUrl or request.imageUrl}'",
                detail=str(e)
            ).model_dump()
        )
    
    # 3. 验证侧位片必须有患者信息
    if request.taskType == 'cephalometric' and not patient_info:
        # 清理临时文件
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message="patientInfo is required for cephalometric tasks",
                detail="Cannot extract valid patient info from DICOM. Please provide patientInfo manually."
            ).model_dump()
        )
    
    # 4. 构造任务参数（伪同步：callback_url=None）
    task_params = {
        "task_id": task_id,
        "task_type": request.taskType,
        "image_path": image_path,
        "patient_info": patient_info,
        "pixel_spacing": pixel_spacing,  # 新增：比例尺信息
        "callback_url": None,
        "metadata": request.metadata or {},
    }
    
    # 5. 提交到 Celery 队列
    logger.info(f"[Pseudo-Sync] Submitting task to Celery: {task_id}")
    celery_result = analyze_task.apply_async(kwargs=task_params)
    
    # 6. 等待 P2 完成
    try:
        timeout = 30
        logger.info(f"[Pseudo-Sync] Waiting for result via polling (timeout={timeout}s): {task_id}")
        
        loop = asyncio.get_event_loop()
        data_dict = await loop.run_in_executor(
            None,
            lambda: _wait_for_celery_result_polling(celery_result, timeout)
        )
        
        logger.info(f"[Pseudo-Sync] Task completed: {task_id}")
        
        # 7. 清理临时文件
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
                logger.info(f"Cleaned up temp file: {f}")
        
        # 8. 清理 Redis 中的临时标记
        try:
            _persistence.delete_task(task_id)
        except Exception as e:
            logger.warning(f"Failed to clean up task marker: {task_id}, {e}")
        
        # 9. 返回结果
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
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
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
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
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
            - imageUrl: 图像 URL（HTTP/HTTPS），与 dicomUrl 二选一
            - dicomUrl: DICOM 文件 URL（HTTP/HTTPS），与 imageUrl 二选一
            - callbackUrl: 回调 URL（HTTP/HTTPS）
            - metadata: 客户端自定义元数据（可选）
            - patientInfo: 患者信息（cephalometric 必需，但 dicomUrl 模式可从 DICOM 解析）
            - pixelSpacing: 比例尺信息（可选，用于非 DICOM 图像）
        
    Returns:
        AnalyzeResponse: 包含 taskId, status, submittedAt, metadata 的响应
        
    Raises:
        HTTPException(400): 参数验证失败、图像下载失败
        HTTPException(409): taskId 已存在
        HTTPException(500): 服务器内部错误（Redis/Celery）
        
    工作流程:
        1. Pydantic 自动验证请求参数（taskId、taskType、imageUrl/dicomUrl 等）
        2. 检查 taskId 是否已存在（防止重复提交）
        3. 下载图像/DICOM 文件
        4. 如果是 DICOM，转换为 JPG 并提取患者信息和比例尺
        5. 保存任务元数据到 Redis
        6. 将任务推入 Celery 队列
        7. 返回 202 Accepted 响应
    """
    from server.tasks import analyze_task
    from tools.dicom_utils import extract_dicom_info_for_inference
    
    logger.info(f"Received async request: taskId={request.taskId}, taskType={request.taskType}, "
                f"imageUrl={request.imageUrl}, dicomUrl={request.dicomUrl}")
    
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
    
    # 2. 下载图像（支持 imageUrl 或 dicomUrl）
    image_path = None
    dicom_path = None
    patient_info = request.patientInfo.model_dump() if request.patientInfo else None
    pixel_spacing = None
    temp_files = []  # 记录需要清理的临时文件
    image_source = "url"
    source_url = request.imageUrl or request.dicomUrl
    
    try:
        if request.dicomUrl:
            # DICOM 模式
            image_source = "dicom"
            dicom_filename = f"{request.taskId}.dcm"
            dicom_path = os.path.join(_upload_dir, dicom_filename)
            temp_files.append(dicom_path)
            
            _image_downloader.download_dicom(request.dicomUrl, dicom_path)
            logger.info(f"DICOM downloaded: {dicom_path}")
            
            # 转换 DICOM 并提取信息
            dicom_info = extract_dicom_info_for_inference(dicom_path, out_dir=_upload_dir)
            image_path = dicom_info["image_path"]
            temp_files.append(image_path)
            
            # 从 DICOM 提取患者信息
            if not patient_info and dicom_info["patient_info"]["gender"]:
                patient_info = dicom_info["patient_info"]
                logger.info(f"Patient info extracted from DICOM: {patient_info}")
            
            # 从 DICOM 提取比例尺
            if dicom_info["pixel_spacing"]["available"]:
                pixel_spacing = {
                    "scale_x": dicom_info["pixel_spacing"]["scale_x"],
                    "scale_y": dicom_info["pixel_spacing"]["scale_y"],
                    "source": "dicom",
                }
                logger.info(f"Pixel spacing extracted from DICOM: {pixel_spacing}")
        else:
            # 普通图像模式
            file_ext = '.jpg'
            image_filename = f"{request.taskId}{file_ext}"
            image_path = os.path.join(_upload_dir, image_filename)
            temp_files.append(image_path)
            
            _image_downloader.download_image(request.imageUrl, image_path)
            logger.info(f"Image downloaded: {request.imageUrl} -> {image_path}")
            
            # 使用请求中的比例尺
            if request.pixelSpacing:
                pixel_spacing = {
                    "scale_x": request.pixelSpacing.scaleX,
                    "scale_y": request.pixelSpacing.scaleY or request.pixelSpacing.scaleX,
                    "source": "request",
                }
                logger.info(f"Pixel spacing from request: {pixel_spacing}")
    except ValueError as e:
        logger.error(f"Image/DICOM validation failed: {e}")
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=11004,
                message=f"Cannot download image/DICOM from '{source_url}'",
                detail=str(e)
            ).model_dump()
        )
    except Exception as e:
        logger.error(f"Image/DICOM download failed: {e}")
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=11004,
                message=f"Cannot download image/DICOM from '{source_url}'",
                detail=str(e)
            ).model_dump()
        )
    
    # 3. 验证侧位片必须有患者信息
    if request.taskType == 'cephalometric' and not patient_info:
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message="patientInfo is required for cephalometric tasks",
                detail="Cannot extract valid patient info from DICOM. Please provide patientInfo manually."
            ).model_dump()
        )
    
    # 4. 构造任务元数据
    submitted_at = time.time()
    metadata_v3 = {
        "taskId": request.taskId,
        "taskType": request.taskType,
        "imageUrl": request.imageUrl,
        "dicomUrl": request.dicomUrl,
        "imagePath": image_path,
        "callbackUrl": request.callbackUrl,
        "metadata": request.metadata or {},
        "patientInfo": patient_info,
        "pixelSpacing": pixel_spacing,
        "submittedAt": submitted_at,
        "imageSource": image_source
    }
    
    # 5. 保存到 Redis
    success = _persistence.save_task(request.taskId, metadata_v3)
    if not success:
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
                logger.info(f"Cleaned up file: {f}")
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                code=50001,
                message="Internal server error",
                detail="Failed to save task metadata to Redis"
            ).model_dump()
        )
    
    # 6. 异步任务入队
    try:
        task_params = {
            "task_id": request.taskId,
            "task_type": request.taskType,
            "image_path": image_path,
            "image_url": source_url,
            "patient_info": patient_info,
            "pixel_spacing": pixel_spacing,  # 新增：比例尺信息
            "callback_url": request.callbackUrl,
            "metadata": request.metadata or {},
        }
        task_result = analyze_task.apply_async(kwargs=task_params)
        logger.info(f"Task queued: {request.taskId}, celery_id={task_result.id}")
    except Exception as e:
        _persistence.delete_task(request.taskId)
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
                logger.info(f"Cleaned up file: {f}")
        logger.error(f"Failed to queue task: {e}")
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                code=50003,
                message="Task queue service unavailable",
                detail=str(e)
            ).model_dump()
        )
    
    # 7. 返回 202 响应
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
    
    因果关系：
        "因"字段（客户端传入，服务端使用）：
        - Metadata
        - AnatomyResults[*].SegmentationMask（髁突/下颌升支/上颌窦的多边形坐标）
        - MaxillarySinus[*].Inflammation, TypeClassification（模型直推）
        - ToothAnalysis[*].FDI, SegmentationMask, Properties, Confidence
        - JointAndMandible.CondyleAssessment.*.Morphology
        - ImplantAnalysis.Items[*].BBox, Confidence
        - ThirdMolarSummary[*].Impactions（模型直推）
        - PeriodontalCondition（模型直推）
        - RootTipDensityAnalysis.Items[*]
        
        "果"字段（服务端重算，客户端传值将被忽略）：
        - CondyleAssessment.OverallSymmetry（髁突对称性）
        - RamusSymmetry, GonialAngleSymmetry（下颌升支/下颌角对称性）
        - MaxillarySinus[*].Pneumatization, RootEntryToothFDI
        - MissingTeeth（缺牙推导）
        - ThirdMolarSummary[*].Level
        - ImplantAnalysis.TotalCount, QuadrantCounts
        - RootTipDensityAnalysis.TotalCount, QuadrantCounts
        - 所有 Detail 字段
    
    Args:
        request: 重算请求
            - taskId: 任务唯一标识，仅用于日志追踪
            - data: 完整的全景片推理结果 JSON（即 example_pano_result.json 格式）
    
    Returns:
        RecalculateResponse: 包含重算后的完整报告（格式与推理接口一致）
    """
    from pipelines.pano.utils.pano_recalculate import recalculate_pano_report
    
    logger.info(f"[Pano Recalculate] Request received: taskId={request.taskId}")
    
    # 1. 校验 taskId
    if not request.taskId:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message="Invalid parameter: taskId is required",
                detail="taskId is required"
            ).model_dump()
        )
    
    # 2. 校验 data 不为空
    if not request.data:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message="Invalid parameter: data is required and cannot be empty",
                detail="data is required and cannot be empty"
            ).model_dump()
        )
    
    # 3. 调用重算逻辑
    logger.info(f"[Pano Recalculate] Starting recalculation: taskId={request.taskId}")
    recalculated_data = recalculate_pano_report(request.data)
    logger.info(f"[Pano Recalculate] Recalculation completed: taskId={request.taskId}")
    
    return RecalculateResponse(
        taskId=request.taskId,
        status="SUCCESS",
        timestamp=datetime.now(timezone.utc).isoformat(),
        metadata=None,  # 接口定义中 metadata 可选
        data=recalculated_data,
        error=None
    )


@app.post("/api/v1/measurements/ceph/recalculate", status_code=200)
def recalculate_ceph_measurements(request: CephRecalculateRequest) -> RecalculateResponse:
    """
    侧位片重算接口（v4 新增）
    
    功能：
        接收客户端修改后的完整推理结果（关键点坐标 + 颈椎分割），
        重新计算所有测量值，生成完整的侧位片报告。
    
    因果关系：
        "因"字段（客户端传入，服务端使用）：
        - ImageSpacing (X, Y, Unit)
        - PatientInformation.Gender, DentalAgeStage
        - LandmarkPositions.Landmarks[*] (Label, X, Y, Confidence, Status)
        - Cervical_Vertebral_Maturity_Stage (Coordinates, SerializedMask, Level, Confidence)
        
        "果"字段（服务端重算，客户端传值将被忽略）：
        - VisibilityMetrics, MissingPointHandling, StatisticalFields
        - LandmarkPositions 统计字段
        - 除 Cervical_Vertebral_Maturity_Stage 外的所有测量值及其 Level
    
    Args:
        request: 重算请求
            - taskId: 任务唯一标识，仅用于日志追踪
            - data: 完整的侧位片推理结果 JSON
    
    Returns:
        RecalculateResponse: 包含重算后的完整报告
    """
    from pipelines.ceph.utils.ceph_recalculate import recalculate_ceph_report
    
    logger.info(f"[Ceph Recalculate] Request received: taskId={request.taskId}")
    
    # 1. 校验 taskId
    if not request.taskId:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message="Invalid parameter: taskId is required",
                detail="taskId is required"
            ).model_dump()
        )
    
    # 2. 校验 data 不为空
    if not request.data:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message="Invalid parameter: data is required and cannot be empty",
                detail="data is required and cannot be empty"
            ).model_dump()
        )
    
    # 3. 校验 patientInfo（侧位片必填）
    if not request.patientInfo:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message="Invalid parameter: patientInfo is required for cephalometric recalculation",
                detail="patientInfo is required for cephalometric recalculation"
            ).model_dump()
        )
    
    # 4. 校验 Gender
    gender = request.patientInfo.gender
    if gender not in ["Male", "Female"]:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message=f"Invalid parameter: patientInfo.gender must be 'Male' or 'Female', got '{gender}'",
                detail=f"patientInfo.gender must be 'Male' or 'Female', got '{gender}'"
            ).model_dump()
        )
    
    # 5. 校验 DentalAgeStage
    dental_age_stage = request.patientInfo.DentalAgeStage
    if dental_age_stage not in ["Permanent", "Mixed"]:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message=f"Invalid parameter: patientInfo.DentalAgeStage must be 'Permanent' or 'Mixed', got '{dental_age_stage}'",
                detail=f"patientInfo.DentalAgeStage must be 'Permanent' or 'Mixed', got '{dental_age_stage}'"
            ).model_dump()
        )
    
    logger.info(f"[Ceph Recalculate] Validation passed: taskId={request.taskId}, gender={gender}, dentalAgeStage={dental_age_stage}")
    
    # 6. 调用重算逻辑
    recalculated_data = recalculate_ceph_report(
        input_data=request.data,
        gender=gender,
        dental_age_stage=dental_age_stage,
    )
    
    logger.info(f"[Ceph Recalculate] Recalculation completed: taskId={request.taskId}")
    
    return RecalculateResponse(
        taskId=request.taskId,
        status="SUCCESS",
        timestamp=datetime.now(timezone.utc).isoformat(),
        metadata=None,
        data=recalculated_data,
        error=None
    )
