# -*- coding: utf-8 -*-
"""
图像下载器
负责从 imageUrl 下载图像文件到本地，包含格式验证、大小限制、超时控制
"""

import requests
import logging
from typing import Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class ImageDownloader:
    """
    HTTP 图像下载管理
    
    负责从 URL 下载图像文件并保存到本地，支持格式验证、大小限制、超时控制。
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化 HTTP 客户端和下载配置
        
        Args:
            config: 配置字典，需包含 image_download 配置项
            
        Raises:
            KeyError: 配置项缺失
        """
        download_config = config.get('image_download', {})
        self.timeout = download_config.get('timeout', 30)
        self.max_size_mb = download_config.get('max_size_mb', 50)
        self.allowed_extensions = download_config.get('allowed_extensions', ['.jpg', '.jpeg', '.png', '.dcm'])
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Xray-Inference-Service/2.0'
        })
        
        logger.info(
            f"ImageDownloader initialized: "
            f"timeout={self.timeout}s, max_size={self.max_size_mb}MB, "
            f"allowed_formats={self.allowed_extensions}"
        )
    
    def download_image(self, image_url: str, save_path: str) -> bool:
        """
        从 URL 下载图像文件并保存到指定路径
        
        Args:
            image_url: 图像 URL（HTTP/HTTPS）
            save_path: 保存路径（本地文件路径）
            
        Returns:
            bool: 是否成功
            
        Raises:
            ValueError: 图像格式不支持或文件过大
            requests.exceptions.Timeout: 下载超时
            requests.exceptions.RequestException: 网络错误
            
        工作流程:
            1. 发送 HEAD 请求检查 Content-Type 和 Content-Length
            2. 验证图像格式（Content-Type 必须以 'image/' 开头）
            3. 验证文件大小（不超过 max_size_mb）
            4. 发送 GET 请求下载文件（流式下载）
            5. 保存到本地文件
        """
        logger.info(f"Starting image download: {image_url}")
        
        # 1. 尝试发送 HEAD 请求检查文件类型和大小
        try:
            head_response = self.session.head(
                image_url, 
                timeout=self.timeout, 
                allow_redirects=True
            )
            head_response.raise_for_status()
            
            # 2. 验证 Content-Type
            content_type = head_response.headers.get('Content-Type', '')
            if content_type:
                self._validate_content_type(content_type)
            
            # 3. 验证文件大小
            content_length = head_response.headers.get('Content-Length')
            if content_length:
                self._validate_file_size(int(content_length))
            else:
                logger.warning(f"Content-Length header not found, skipping size validation")
        except requests.HTTPError as e:
            if e.response.status_code == 405:
                # HEAD 方法不支持，直接下载
                logger.warning(f"HEAD method not supported for {image_url}, will validate during download")
            else:
                raise
        
        # 4. 下载文件（流式）
        response = self.session.get(
            image_url, 
            timeout=self.timeout, 
            stream=True
        )
        response.raise_for_status()
        
        # 4.1 如果HEAD请求未验证Content-Type，现在验证
        content_type = response.headers.get('Content-Type', '')
        if content_type:
            self._validate_content_type(content_type)
        
        # 5. 保存到本地
        save_dir = Path(save_path).parent
        save_dir.mkdir(parents=True, exist_ok=True)
        
        downloaded_size = 0
        max_size_bytes = self.max_size_mb * 1024 * 1024
        
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    
                    # 二次验证：检查下载过程中的大小
                    if downloaded_size > max_size_bytes:
                        f.close()
                        Path(save_path).unlink(missing_ok=True)
                        raise ValueError(
                            f"File size exceeds {self.max_size_mb}MB limit during download"
                        )
        
        logger.info(
            f"Image downloaded successfully: {image_url} -> {save_path} "
            f"({downloaded_size / 1024:.2f} KB)"
        )
        return True
    
    def _validate_content_type(self, content_type: str) -> None:
        """
        验证 HTTP Content-Type 是否为图像类型
        
        Args:
            content_type: Content-Type 头
            
        Raises:
            ValueError: Content-Type 不是图像类型
        """
        if not content_type.startswith('image/'):
            raise ValueError(
                f"Unsupported Content-Type: {content_type}. "
                f"Only image/* types are allowed."
            )
        logger.debug(f"Content-Type validated: {content_type}")
    
    def _validate_file_size(self, content_length: int) -> None:
        """
        验证文件大小是否在限制内
        
        Args:
            content_length: Content-Length 字节数
            
        Raises:
            ValueError: 文件大小超过限制
        """
        max_size_bytes = self.max_size_mb * 1024 * 1024
        if content_length > max_size_bytes:
            raise ValueError(
                f"File size ({content_length / 1024 / 1024:.2f} MB) exceeds "
                f"{self.max_size_mb}MB limit"
            )
        logger.debug(f"File size validated: {content_length / 1024:.2f} KB")

