# -*- coding: utf-8 -*-
"""
API 路由定义
负责处理 HTTP 请求，实现 202/400 逻辑
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from server import load_config
from server.schemas import AnalyzeRequest, AnalyzeResponse, ErrorResponse, PatientInfo
from typing import Optional
import logging
import os
import time
import json

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
async def analyze(
    taskId: str = Form(..., description="任务唯一标识（客户端提供，UUID v4 格式）"),
    taskType: str = Form(..., description="任务类型（panoramic/cephalometric）"),
    callbackUrl: str = Form(..., description="回调 URL（HTTP/HTTPS）"),
    image: Optional[UploadFile] = File(default=None, description="图像文件（可选，优先使用）"),
    imageUrl: Optional[str] = Form(default=None, description="图像 URL（可选，image 不存在时使用）"),
    metadata: Optional[str] = Form(default=None, description="客户端自定义元数据（JSON 字符串，可选）"),
    patientInfo: Optional[str] = Form(default=None, description="患者信息（JSON 字符串，cephalometric 必需）")
):
    """
    接收推理请求（v2 混合协议：支持文件上传或 URL 下载）
    
    Args:
        taskId: 任务唯一标识（客户端提供，UUID v4 格式）
        taskType: 任务类型（panoramic/cephalometric）
        callbackUrl: 回调 URL（HTTP/HTTPS）
        image: 图像文件（可选，优先使用）
        imageUrl: 图像 URL（可选，image 不存在时使用）
        metadata: 客户端自定义元数据（JSON 字符串，可选）
        patientInfo: 患者信息（JSON 字符串，cephalometric 必需）
        
    Returns:
        AnalyzeResponse: 包含 taskId, status, submittedAt, metadata 的响应
        
    Raises:
        HTTPException(400): 参数验证失败、图像下载/上传失败
        HTTPException(409): taskId 已存在
        HTTPException(500): 服务器内部错误（Redis/Celery）
        
    工作流程:
        1. 验证参数（taskId、taskType、image/imageUrl 二选一）
        2. 检查 taskId 是否已存在（防止重复提交）
        3. 保存图像文件（优先使用 image，否则从 imageUrl 下载）
        4. 保存任务元数据到 Redis（v2 扩展字段）
        5. 将任务推入 Celery 队列
        6. 返回 202 Accepted 响应（v2 格式）
    """
    from datetime import datetime, timezone
    import uuid
    
    # 延迟导入 analyze_task 避免循环导入
    from server.tasks import analyze_task
    
    # 1. 验证 taskId 格式
    try:
        uuid.UUID(taskId, version=4)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message="Request validation failed",
                detail="taskId must be a valid UUID v4"
            ).model_dump()
        )
    
    # 2. 验证 taskType
    if taskType not in ['panoramic', 'cephalometric']:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message="Request validation failed",
                detail="taskType must be either 'panoramic' or 'cephalometric'"
            ).model_dump()
        )
    
    # 3. 验证 callbackUrl
    if not (callbackUrl.startswith('http://') or callbackUrl.startswith('https://')):
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message="Request validation failed",
                detail="callbackUrl must be a valid HTTP/HTTPS URL"
            ).model_dump()
        )
    
    # 4. 验证至少提供 image 或 imageUrl 之一
    if not image and not imageUrl:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message="Request validation failed",
                detail="Either 'image' (file) or 'imageUrl' must be provided"
            ).model_dump()
        )
    
    # 5. 解析 metadata（如果提供）
    client_metadata = {}
    if metadata:
        try:
            client_metadata = json.loads(metadata)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    code=10001,
                    message="Request validation failed",
                    detail="metadata must be valid JSON"
                ).model_dump()
            )
    
    # 6. 解析并验证 patientInfo（如果提供）
    patient_info_obj = None
    if patientInfo:
        try:
            patient_info_dict = json.loads(patientInfo)
            patient_info_obj = PatientInfo(**patient_info_dict)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    code=10001,
                    message="Request validation failed",
                    detail="patientInfo must be valid JSON"
                ).model_dump()
            )
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    code=10001,
                    message="Request validation failed",
                    detail=f"patientInfo validation failed: {str(e)}"
                ).model_dump()
            )
    
    # 7. 验证 cephalometric 必须提供 patientInfo
    if taskType == 'cephalometric' and not patient_info_obj:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=10001,
                message="Request validation failed",
                detail="patientInfo is required when taskType is 'cephalometric'"
            ).model_dump()
        )
    
    logger.info(f"Received taskId: {taskId}, taskType: {taskType}, has_file: {image is not None}, has_url: {imageUrl is not None}")
    
    # 8. 检查 taskId 是否已存在
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
    
    # 9. 保存图像文件（优先使用 image，否则下载 imageUrl）
    image_source = None  # 记录图像来源：'file' 或 'url'
    
    if image:
        # 优先使用上传的文件
        image_source = 'file'
        allowed_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.dcm']
        file_ext = os.path.splitext(image.filename)[1].lower() if image.filename else '.jpg'
        
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
        
        image_filename = f"{taskId}{file_ext}"
        image_path = os.path.join(_upload_dir, image_filename)
        
        try:
            # 异步保存上传文件
            with open(image_path, "wb") as buffer:
                content = await image.read()
                buffer.write(content)
            logger.info(f"Image uploaded: {image.filename} -> {image_path}")
        except Exception as e:
            logger.error(f"Image upload failed: {e}")
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    code=10004,
                    message="Image upload failed",
                    detail=str(e)
                ).model_dump()
            )
    else:
        # 使用 imageUrl 下载
        image_source = 'url'
        
        if not (imageUrl.startswith('http://') or imageUrl.startswith('https://')):
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    code=10001,
                    message="Request validation failed",
                    detail="imageUrl must be a valid HTTP/HTTPS URL"
                ).model_dump()
            )
        
        file_ext = '.jpg'
        image_filename = f"{taskId}{file_ext}"
        image_path = os.path.join(_upload_dir, image_filename)
        
        try:
            _image_downloader.download_image(imageUrl, image_path)
            logger.info(f"Image downloaded: {imageUrl} -> {image_path}")
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
    
    # 10. 构造任务元数据 v2
    submitted_at = time.time()
    metadata_v2 = {
        "taskId": taskId,
        "taskType": taskType,
        "imageUrl": imageUrl if image_source == 'url' else f"uploaded:{image.filename if image else 'unknown'}",
        "imagePath": image_path,
        "callbackUrl": callbackUrl,
        "metadata": client_metadata,
        "patientInfo": patient_info_obj.model_dump() if patient_info_obj else None,
        "submittedAt": submitted_at,
        "imageSource": image_source  # 记录图像来源
    }
    
    # 11. 保存到 Redis
    success = _persistence.save_task(taskId, metadata_v2)
    if not success:
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
    
    # 12. 异步任务入队
    try:
        task_result = analyze_task.delay(taskId)
        logger.info(f"Task queued: {taskId}, celery_id={task_result.id}, source={image_source}")
    except Exception as e:
        _persistence.delete_task(taskId)
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
    
    # 13. 返回 202 响应 v2
    return AnalyzeResponse(
        taskId=taskId,
        status="QUEUED",
        submittedAt=datetime.fromtimestamp(submitted_at, tz=timezone.utc).isoformat(),
        metadata=client_metadata
    )
