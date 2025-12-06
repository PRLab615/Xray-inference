# -*- coding: utf-8 -*-
"""
Pipeline 基础类
定义所有推理管道的通用接口和共享功能
"""

from abc import ABC, abstractmethod
import logging
import os


class BasePipeline(ABC):
    """
    推理管道基类
    
    所有具体的 Pipeline（PanoPipeline, CephPipeline）必须继承此类并实现 run() 方法。
    提供统一的接口规范和共享的工具方法。
    """
    
    def __init__(self):
        """
        初始化 Pipeline
        
        设置日志记录器和 pipeline_type（子类需覆盖）
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.pipeline_type = "base"  # 子类需覆盖
        self.is_mock_mode = False  # Mock模式标志：当模型加载失败时启用
        self.logger.info(f"{self.__class__.__name__} initialized")
    
    @abstractmethod
    def run(self, image_path: str, **kwargs) -> dict:
        """
        执行推理流程（抽象方法，子类必须实现）
        
        Args:
            image_path: 图像文件路径
            **kwargs: 额外参数（如 patient_info）
            
        Returns:
            dict: 完整的 data 字段，符合《接口定义.md》规范
            
        Raises:
            NotImplementedError: 子类未实现此方法
            
        Note:
            - 子类必须实现此方法
            - 返回的 dict 必须符合对应任务类型的 JSON 规范
        """
        raise NotImplementedError("Subclass must implement run() method")
    
    def _load_image(self, image_path: str):
        """
        加载图像文件
        
        Args:
            image_path: 图像文件路径
            
        Returns:
            图像对象（v3 暂返回 None，v4 实现真实加载）
            
        Raises:
            FileNotFoundError: 文件不存在
            
        Note:
            - v3: 仅验证文件存在性
            - v4: 实现真实的图像加载逻辑（JPG/PNG/DICOM）
        """
        if not os.path.exists(image_path):
            self.logger.error(f"Image file not found: {image_path}")
            raise FileNotFoundError(f"Image file not found: {image_path}")
        
        self.logger.info(f"Image file validated: {image_path}")
        # v3 占位：返回 None
        return None
    
    def _validate_image(self, image) -> bool:
        """
        验证图像是否有效
        
        Args:
            image: 图像对象
            
        Returns:
            bool: 图像是否有效
            
        Note:
            - v3: 简单的 None 检查（在 v3 中始终为 None，所以跳过检查）
            - v4: 实现真实的验证逻辑（尺寸、格式等）
        """
        # v3 占位：仅检查是否为 None（在 v3 中始终为 None，所以跳过检查）
        return True
    
    def _log_step(self, step_name: str, message: str = ""):
        """
        统一的步骤日志记录
        
        Args:
            step_name: 步骤名称
            message: 附加信息（可选）
            
        Note:
            - 使用统一的日志格式：[pipeline_type] step_name: message
        """
        log_msg = f"[{self.pipeline_type}] {step_name}"
        if message:
            log_msg += f": {message}"
        self.logger.info(log_msg)
