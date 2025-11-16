# -*- coding: utf-8 -*-
"""
API 路由定义
负责处理 HTTP 请求，实现 202/400 逻辑
"""

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from server import load_config
from server.schemas import AnalyzeRequest, AnalyzeResponse, ErrorResponse
import logging
import os
import time
import shutil

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
_upload_dir = None


@app.on_event("startup")
async def startup_event():
    """
    应用启动事件
    
    初始化全局单例:
        - TaskPersistence: Redis 持久化客户端
        - upload_dir: 文件上传目录路径
    """
    global _persistence, _upload_dir
    
    from server.core.persistence import TaskPersistence
    
    config = app.state.config
    _persistence = TaskPersistence(config)
    _upload_dir = config['api']['upload_dir']
    
    logger.info(f"API service initialized, upload_dir: {_upload_dir}")


# ==================== 核心 API 接口 ====================

@app.post("/api/v1/analyze", status_code=202)
async def analyze(
    taskId: str = Form(...),
    taskType: str = Form(...),
    callbackUrl: str = Form(...),
    image: UploadFile = File(...)
):
    """
    接收推理请求
    
    Args:
        taskId: 任务唯一标识（UUID v4 格式）
        taskType: 任务类型（pano/ceph）
        callbackUrl: 回调 URL（http/https）
        image: 上传的图像文件
        
    Returns:
        AnalyzeResponse: 包含 taskId, status, message 的响应
        
    Raises:
        HTTPException(400): 参数验证失败或文件格式不支持
        HTTPException(409): taskId 已存在
        HTTPException(500): 服务器内部错误（Redis/Celery）
        
    工作流程:
        1. 验证参数格式（使用 Pydantic）
        2. 检查 taskId 是否已存在
        3. 验证图像文件格式
        4. 保存上传文件到本地
        5. 保存任务元数据到 Redis
        6. 将任务推入 Celery 队列
        7. 返回 202 Accepted 响应
    """
    # 延迟导入 analyze_task 避免循环导入
    from server.tasks import analyze_task
    
    # 1. 验证参数格式
    try:
        request_data = AnalyzeRequest(
            taskId=taskId,
            taskType=taskType,
            callbackUrl=callbackUrl
        )
    except ValueError as e:
        logger.error(f"Validation failed: {e}")
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message="Request validation failed",
                detail=str(e)
            ).model_dump()
        )
    
    # 2. 检查 taskId 是否已存在
    if _persistence.task_exists(taskId):
        logger.warning(f"Task already exists: {taskId}")
        raise HTTPException(
            status_code=409,
            detail=ErrorResponse(
                code=10002,
                message="Task ID already exists",
                detail=f"taskId {taskId} is already in use"
            ).model_dump()
        )
    
    # 3. 验证图像格式
    allowed_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.dcm']
    file_ext = os.path.splitext(image.filename)[1].lower()
    if file_ext not in allowed_extensions:
        logger.error(f"Unsupported image format: {file_ext}")
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10003,
                message="Unsupported image format",
                detail=f"Allowed formats: {', '.join(allowed_extensions)}"
            ).model_dump()
        )
    
    # 4. 保存上传文件
    image_filename = f"{taskId}{file_ext}"
    image_path = os.path.join(_upload_dir, image_filename)
    
    with open(image_path, "wb") as buffer:
        shutil.copyfileobj(image.file, buffer)
    
    logger.info(f"Image saved: {image_path}")
    
    # 5. 保存任务元数据到 Redis
    metadata = {
        "taskId": taskId,
        "taskType": taskType,
        "imagePath": image_path,
        "callbackUrl": callbackUrl,
        "createdAt": time.time()
    }
    
    success = _persistence.save_task(taskId, metadata)
    if not success:
        # 清理已上传的文件
        if os.path.exists(image_path):
            os.remove(image_path)
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                code=10001,
                message="Failed to save task metadata",
                detail="Redis operation failed"
            ).model_dump()
        )
    
    # 6. 异步任务入队
    task_result = analyze_task.delay(taskId)
    logger.info(f"Task queued: {taskId}, celery_id={task_result.id}")
    
    # 7. 返回 202 响应
    return AnalyzeResponse(
        taskId=taskId,
        status="accepted",
        message="Task queued successfully"
    )
