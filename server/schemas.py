# -*- coding: utf-8 -*-
"""
Pydantic 请求体验证 v2
定义请求和响应的数据模型（升级版本）
"""

from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, Dict, Any
import uuid


class PatientInfo(BaseModel):
    """
    患者信息模型（侧位片必需）
    
    Attributes:
        gender: 性别（Male/Female）
        DentalAgeStage: 牙期（Permanent/Mixed）
    """
    gender: str
    DentalAgeStage: str
    
    @field_validator('gender')
    @classmethod
    def validate_gender(cls, v: str) -> str:
        """
        验证性别字段的合法性
        
        Args:
            v: 待验证的性别
            
        Returns:
            str: 验证通过的性别
            
        Raises:
            ValueError: 性别不是 Male 或 Female
        """
        if v not in ['Male', 'Female']:
            raise ValueError("gender must be either 'Male' or 'Female'")
        return v
    
    @field_validator('DentalAgeStage')
    @classmethod
    def validate_dental_age_stage(cls, v: str) -> str:
        """
        验证牙期字段的合法性
        
        Args:
            v: 待验证的牙期
            
        Returns:
            str: 验证通过的牙期
            
        Raises:
            ValueError: 牙期不是 Permanent 或 Mixed
        """
        if v not in ['Permanent', 'Mixed']:
            raise ValueError("DentalAgeStage must be either 'Permanent' or 'Mixed'")
        return v


class AnalyzeRequest(BaseModel):
    """
    分析请求模型 v2
    
    Attributes:
        taskId: 任务唯一标识（客户端提供，UUID v4 格式）
        taskType: 任务类型（panoramic/cephalometric）
        imageUrl: 图像 URL（HTTP/HTTPS）
        callbackUrl: 回调 URL（HTTP/HTTPS）
        metadata: 客户端自定义元数据（可选）
        patientInfo: 患者信息（侧位片必需）
    """
    taskId: str
    taskType: str
    imageUrl: str
    callbackUrl: str
    metadata: Optional[Dict[str, Any]] = None
    patientInfo: Optional[PatientInfo] = None
    
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
            ValueError: taskType 不是 panoramic 或 cephalometric
        """
        if v not in ['panoramic', 'cephalometric']:
            raise ValueError("taskType must be either 'panoramic' or 'cephalometric'")
        return v
    
    @field_validator('imageUrl')
    @classmethod
    def validate_image_url(cls, v: str) -> str:
        """
        验证 imageUrl 是否为有效的 HTTP/HTTPS URL
        
        Args:
            v: 待验证的 URL
            
        Returns:
            str: 验证通过的 URL
            
        Raises:
            ValueError: URL 不是有效的 HTTP/HTTPS 地址
        """
        if not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError('imageUrl must be a valid HTTP/HTTPS URL')
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
    
    @model_validator(mode='after')
    def validate_patient_info_required(self):
        """
        验证侧位片必须提供 patientInfo
        
        对于 taskType 为 'cephalometric' 的请求，必须包含 patientInfo，
        且 gender 和 DentalAgeStage 都必须存在。
        
        Returns:
            self: 验证通过的模型实例
            
        Raises:
            ValueError: 侧位片缺少必需的 patientInfo
        """
        if self.taskType == 'cephalometric':
            if not self.patientInfo:
                raise ValueError("patientInfo is required when taskType is 'cephalometric'")
            if not self.patientInfo.gender or not self.patientInfo.DentalAgeStage:
                raise ValueError("gender and DentalAgeStage are required in patientInfo for cephalometric tasks")
        return self


class AnalyzeResponse(BaseModel):
    """
    分析响应模型 v2（202 Accepted）
    
    Attributes:
        taskId: 任务 ID（回显客户端提供的 taskId）
        status: 任务状态（固定值 "QUEUED"）
        submittedAt: 提交时间（ISO8601 格式）
        metadata: 回显客户端 metadata
    """
    taskId: str
    status: str
    submittedAt: str
    metadata: Optional[Dict[str, Any]] = None


class RequestParameters(BaseModel):
    """
    请求参数记录（回调中使用）
    
    Attributes:
        taskType: 任务类型
        imageUrl: 原始图像 URL
    """
    taskType: str
    imageUrl: str


class ErrorDetail(BaseModel):
    """
    错误详情模型 v2
    
    Attributes:
        code: 错误码
        message: 开发者调试信息
        displayMessage: 用户友好提示
    """
    code: int
    message: str
    displayMessage: str


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
    回调负载模型 v2
    
    Attributes:
        taskId: 任务 ID
        status: 状态（SUCCESS/FAILURE）
        timestamp: 完成时间（ISO8601 格式）
        metadata: 客户端 metadata
        requestParameters: 原始请求参数
        data: 成功时的结果数据（nullable）
        error: 失败时的错误信息（nullable）
    """
    taskId: str
    status: str
    timestamp: str
    metadata: Dict[str, Any]
    requestParameters: RequestParameters
    data: Optional[Dict[str, Any]] = None
    error: Optional[ErrorDetail] = None

