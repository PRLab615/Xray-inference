# -*- coding: utf-8 -*-
"""
API 服务启动入口 (P1)
负责处理 HTTP 请求，验证参数，将任务推入队列，立即返回 202 响应
"""

import uvicorn
import os
import logging
from server import load_config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """
    启动 API 服务
    
    工作流程：
    1. 加载配置文件
    2. 创建上传目录
    3. 启动 Uvicorn 服务器
    """
    # 加载配置
    config = load_config()
    
    # 创建上传目录
    upload_dir = config['api']['upload_dir']
    os.makedirs(upload_dir, exist_ok=True)
    logger.info(f"Upload directory: {upload_dir}")
    
    # 启动 Uvicorn
    host = config['api']['host']
    port = config['api']['port']
    
    logger.info(f"Starting API service on {host}:{port}")
    uvicorn.run(
        "server.api:app",
        host=host,
        port=port,
        log_level="info",
        reload=False
    )


if __name__ == "__main__":
    main()

