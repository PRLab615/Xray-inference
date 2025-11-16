# -*- coding: utf-8 -*-
"""
回调管理器
实现 POST 回调，包含超时逻辑
第一版实现：单次尝试，不含重试机制
"""

import requests
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class CallbackManager:
    """
    HTTP 回调管理
    
    负责向客户端发送推理结果，支持超时控制。
    第一版实现单次尝试，不含重试机制（重试功能留待第二版）。
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化 HTTP 客户端
        
        Args:
            config: 配置字典，需包含 callback 配置项
            
        Raises:
            KeyError: 配置项缺失
        """
        self.timeout = config['callback']['timeout']
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'Xray-Inference-Service/1.0'
        })
        logger.info(f"CallbackManager initialized with timeout={self.timeout}s")
    
    def send_callback(self, callback_url: str, payload: Dict[str, Any]) -> bool:
        """
        发送回调请求到指定 URL
        
        Args:
            callback_url: 回调 URL（HTTP/HTTPS）
            payload: 回调负载，包含 taskId, data, error
            
        Returns:
            bool: 回调是否成功（HTTP 200 视为成功）
            
        Note:
            - 第一版实现单次尝试，不含重试
            - 超时、连接错误、HTTP 错误均视为失败
            - 仅 HTTP 200 视为成功，其他状态码视为失败
        """
        try:
            logger.info(f"Sending callback to: {callback_url}")
            response = self.session.post(
                callback_url,
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                logger.info(f"Callback success: {callback_url}, taskId={payload.get('taskId')}")
                return True
            else:
                logger.error(
                    f"Callback failed: {callback_url}, "
                    f"status={response.status_code}, "
                    f"response={response.text[:200]}"
                )
                return False
                
        except requests.Timeout:
            logger.error(f"Callback timeout: {callback_url}, timeout={self.timeout}s")
            return False
            
        except requests.ConnectionError as e:
            logger.error(f"Callback connection error: {callback_url}, error={str(e)}")
            return False
            
        except requests.RequestException as e:
            logger.error(f"Callback request error: {callback_url}, error={str(e)}")
            return False

