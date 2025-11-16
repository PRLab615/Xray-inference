# -*- coding: utf-8 -*-
"""
API 路由定义
负责处理 HTTP 请求，实现 202/400 逻辑
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from server import load_config
from server.schemas import AnalyzeRequest, AnalyzeResponse, ErrorResponse
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
    应用启动事件（v2 扩展）
    
    初始化全局单例:
        - TaskPersistence: Redis 持久化客户端
        - ImageDownloader: 图像下载器（v2 新增）
        - upload_dir: 文件上传目录路径
    """
    global _persistence, _image_downloader, _upload_dir
    
    from server.core.persistence import TaskPersistence
    from server.utils.image_downloader import ImageDownloader
    
    config = app.state.config
    _persistence = TaskPersistence(config)
    _image_downloader = ImageDownloader(config)  # v2 新增
    _upload_dir = config['api']['upload_dir']
    
    logger.info(f"API service initialized (v2), upload_dir: {_upload_dir}")


# ==================== 核心 API 接口 ====================

@app.post("/api/v1/analyze", status_code=202)
async def analyze(request: AnalyzeRequest):
    """
    接收推理请求（v2 协议）
    
    Args:
        request: AnalyzeRequest 对象（JSON 请求体）
            - taskId: 任务唯一标识（客户端提供，UUID v4 格式）
            - taskType: 任务类型（panoramic/cephalometric）
            - imageUrl: 图像 URL（HTTP/HTTPS）
            - callbackUrl: 回调 URL（HTTP/HTTPS）
            - metadata: 客户端自定义元数据（可选）
            - patientInfo: 患者信息（侧位片必需）
        
    Returns:
        AnalyzeResponse: 包含 taskId, status, submittedAt, metadata 的响应
        
    Raises:
        HTTPException(400): 参数验证失败、图像下载失败
        HTTPException(409): taskId 已存在
        HTTPException(500): 服务器内部错误（Redis/Celery）
        
    工作流程:
        1. 使用客户端提供的 taskId（Pydantic 已验证格式）
        2. 检查 taskId 是否已存在（防止重复提交）
        3. 下载图像文件（从 imageUrl）
        4. 保存任务元数据到 Redis（v2 扩展字段）
        5. 将任务推入 Celery 队列
        6. 返回 202 Accepted 响应（v2 格式）
    """
    from datetime import datetime, timezone
    
    # 延迟导入 analyze_task 避免循环导入
    from server.tasks import analyze_task
    
    # 1. 使用客户端提供的 taskId
    task_id = request.taskId
    logger.info(f"Received taskId: {task_id}, taskType: {request.taskType}")
    
    # 2. 检查 taskId 是否已存在
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
    
    # 3. 确定文件扩展名（默认 .jpg）
    file_ext = '.jpg'
    image_filename = f"{task_id}{file_ext}"
    image_path = os.path.join(_upload_dir, image_filename)
    
    # 4. 下载图像文件
    try:
        _image_downloader.download_image(request.imageUrl, image_path)
        logger.info(f"Image downloaded: {request.imageUrl} -> {image_path}")
    except ValueError as e:
        # 格式验证或大小限制错误
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
        # 网络错误、超时等
        logger.error(f"Image download failed: {e}")
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10004,
                message="Image download failed",
                detail=str(e)
            ).model_dump()
        )
    
    # 5. 构造任务元数据 v2
    submitted_at = time.time()
    metadata_v2 = {
        "taskId": task_id,
        "taskType": request.taskType,
        "imageUrl": request.imageUrl,
        "imagePath": image_path,
        "callbackUrl": request.callbackUrl,
        "metadata": request.metadata or {},
        "patientInfo": request.patientInfo.model_dump() if request.patientInfo else None,
        "submittedAt": submitted_at
    }
    
    # 6. 保存到 Redis
    success = _persistence.save_task(task_id, metadata_v2)
    if not success:
        # 清理已下载的文件
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
    
    # 7. 异步任务入队
    try:
        task_result = analyze_task.delay(task_id)
        logger.info(f"Task queued: {task_id}, celery_id={task_result.id}")
    except Exception as e:
        # 清理元数据和文件
        _persistence.delete_task(task_id)
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
    
    # 8. 返回 202 响应 v2
    return AnalyzeResponse(
        taskId=task_id,
        status="QUEUED",
        submittedAt=datetime.fromtimestamp(submitted_at, tz=timezone.utc).isoformat(),
        metadata=request.metadata
    )
