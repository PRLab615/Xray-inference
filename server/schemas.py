# -*- coding: utf-8 -*-
"""
Pydantic 请求体验证
定义请求和响应的数据模型
"""

from pydantic import BaseModel, field_validator
from typing import Optional, Dict, Any
import uuid


class AnalyzeRequest(BaseModel):
    """
    分析请求模型
    
    Attributes:
        taskId: 任务唯一标识（UUID v4）
        taskType: 任务类型（pano/ceph）
        callbackUrl: 回调 URL（HTTP/HTTPS）
    """
    taskId: str
    taskType: str
    callbackUrl: str
    
    @field_validator('taskId')
    @classmethod
    def validate_task_id(cls, v: str) -> str:
        """
        验证 taskId 是否为有效的 UUID v4 格式
        
        Args:
            v: 待验证的 taskId
            
        Returns:
            str: 验证通过的 taskId
            
        Raises:
            ValueError: taskId 不是有效的 UUID v4
        """
        try:
            uuid.UUID(v, version=4)
            return v
        except ValueError:
            raise ValueError('taskId must be a valid UUID v4')
    
    @field_validator('taskType')
    @classmethod
    def validate_task_type(cls, v: str) -> str:
        """
        验证 taskType 是否在允许的范围内
        
        Args:
            v: 待验证的 taskType
            
        Returns:
            str: 验证通过的 taskType
            
        Raises:
            ValueError: taskType 不是 pano 或 ceph
        """
        if v not in ['pano', 'ceph']:
            raise ValueError('taskType must be either pano or ceph')
        return v
    
    @field_validator('callbackUrl')
    @classmethod
    def validate_callback_url(cls, v: str) -> str:
        """
        验证 callbackUrl 是否为有效的 HTTP/HTTPS URL
        
        Args:
            v: 待验证的 URL
            
        Returns:
            str: 验证通过的 URL
            
        Raises:
            ValueError: URL 不是有效的 HTTP/HTTPS 地址
        """
        if not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError('callbackUrl must be a valid HTTP/HTTPS URL')
        return v


class AnalyzeResponse(BaseModel):
    """
    分析响应模型（202 Accepted）
    
    Attributes:
        taskId: 任务 ID
        status: 任务状态
        message: 响应消息
    """
    taskId: str
    status: str
    message: str


class ErrorDetail(BaseModel):
    """
    错误详情模型
    
    Attributes:
        code: 错误码
        message: 错误描述
    """
    code: int
    message: str


class ErrorResponse(BaseModel):
    """
    错误响应模型
    
    Attributes:
        code: 错误码
        message: 错误消息
        detail: 详细信息（可选）
    """
    code: int
    message: str
    detail: Optional[str] = None


class CallbackPayload(BaseModel):
    """
    回调负载模型
    
    Attributes:
        taskId: 任务 ID
        data: 成功时的结果数据（nullable）
        error: 失败时的错误信息（nullable）
    """
    taskId: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[ErrorDetail] = None

