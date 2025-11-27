# -*- coding: utf-8 -*-
"""
API 路由定义
负责处理 HTTP 请求，实现 202/400 逻辑
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from server import load_config
from server.schemas import AnalyzeRequest, AnalyzeResponse, ErrorResponse
from datetime import datetime, timezone
import logging
import os
import time

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
_image_downloader = None  # v2 新增
_upload_dir = None


@app.on_event("startup")
async def startup_event():
    """
    应用启动事件（v3 纯 JSON）
    
    初始化全局单例:
        - TaskPersistence: Redis 持久化客户端
        - ImageDownloader: 图像下载器（从 URL 下载）
        - upload_dir: 图像存储目录路径
    """
    global _persistence, _image_downloader, _upload_dir
    
    from server.core.persistence import TaskPersistence
    from server.utils.image_downloader import ImageDownloader
    
    config = app.state.config
    _persistence = TaskPersistence(config)
    _image_downloader = ImageDownloader(config)
    _upload_dir = config['api']['upload_dir']
    
    logger.info(f"API service initialized (v3 JSON), image_dir: {_upload_dir}")


# ==================== 核心 API 接口 ====================

@app.post("/api/v1/analyze", status_code=202)
async def analyze(request: AnalyzeRequest):
    """
    接收推理请求（v3 纯 JSON 协议：只支持 URL 下载）
    
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
    
    logger.info(f"Received JSON request: taskId={request.taskId}, taskType={request.taskType}, imageUrl={request.imageUrl}")
    
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
    
    # 2. 下载图像（只支持 URL）
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
    
    # 3. 构造任务元数据 v3
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
        "imageSource": "url"  # v3 只支持 URL
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
    
    # 5. 异步任务入队
    try:
        task_result = analyze_task.delay(request.taskId)
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
