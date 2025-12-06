"""
S3 权重获取工具

负责：
- 依据约定的 S3/MinIO 配置，将远端权重文件下载到本地缓存目录
- 如本地已存在缓存，可直接复用
- 向调用方返回可用于模型加载的本地文件路径
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import (
    ClientError, 
    BotoCoreError, 
    EndpointConnectionError, 
    ConnectionClosedError,
    NoCredentialsError,
    PartialCredentialsError
)

# 捕获底层网络库的异常
try:
    import requests
    from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout, RequestException
except ImportError:
    # requests 可能未安装，但不影响主要功能
    RequestsConnectionError = None
    Timeout = None
    RequestException = None

try:
    import torch  # 可选：供 load_state_dict_from_s3 使用
except Exception:  # pragma: no cover - 某些环境可能没有 torch
    torch = None  # type: ignore

S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL', 'http://192.168.1.17:19000')
S3_ACCESS_KEY = os.getenv('S3_ACCESS_KEY', 'root')
S3_SECRET_KEY = os.getenv('S3_SECRET_KEY', 'Sitonholy@2023')
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', 'teeth')

LOCAL_WEIGHTS_DIR = Path(os.getenv('WEIGHTS_CACHE_DIR', './cached_weights'))


class WeightFetchError(RuntimeError):
    """抛出权重下载或加载失败时的错误。"""


def get_s3_client():
    """初始化并返回 S3 客户端"""
    return boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )


def _normalize_key(relative_path: str) -> str:
    if not relative_path:
        raise ValueError("s3_relative_path must not be empty")
    return relative_path.lstrip('/').replace('\\', '/')


def ensure_weight_file(s3_relative_path: str, *, force_download: bool = False) -> str:
    """
    确保指定 S3 key 的权重文件已缓存到本地。

    Args:
        s3_relative_path: S3 中的 Key（不含 bucket），例如 'weights/ceph/model.pt'
        force_download: 是否忽略本地缓存重新下载

    Returns:
        str: 本地文件的绝对路径，可直接传给模型加载接口
    """

    sanitized_key = _normalize_key(s3_relative_path)
    local_path = LOCAL_WEIGHTS_DIR / sanitized_key
    local_path.parent.mkdir(parents=True, exist_ok=True)

    if not local_path.exists() or force_download:
        client = get_s3_client()
        try:
            client.download_file(S3_BUCKET_NAME, sanitized_key, str(local_path))
        except (ClientError, BotoCoreError, EndpointConnectionError, ConnectionClosedError, 
                NoCredentialsError, PartialCredentialsError) as exc:
            # 捕获所有 boto3/botocore 相关的连接和下载错误
            error_code = None
            if isinstance(exc, ClientError):
                error_code = exc.response.get('Error', {}).get('Code')
            
            message = (
                f"S3 download failed (bucket={S3_BUCKET_NAME}, key={sanitized_key}"
                + (f", code={error_code}" if error_code else "")
                + f"): {exc}"
            )
            raise WeightFetchError(message) from exc
        except Exception as exc:
            # 捕获底层网络库的异常（requests, urllib3 等）
            # 检查异常类型而不是错误消息，避免误判
            exc_type = type(exc).__name__
            exc_module = type(exc).__module__
            
            # 检查是否是网络/连接相关的异常
            is_network_error = (
                # requests 异常
                (RequestsConnectionError and isinstance(exc, RequestsConnectionError)) or
                (Timeout and isinstance(exc, Timeout)) or
                (RequestException and isinstance(exc, RequestException)) or
                # urllib3 异常
                'urllib3' in exc_module or
                'urllib' in exc_module or
                # socket 异常
                'socket' in exc_module or
                # 其他常见的网络异常类型
                'Connection' in exc_type or
                'Timeout' in exc_type or
                'Network' in exc_type
            )
            
            if is_network_error:
                message = (
                    f"S3 download failed (bucket={S3_BUCKET_NAME}, key={sanitized_key}): {exc}"
                )
                raise WeightFetchError(message) from exc
            # 其他未知错误直接抛出（可能是代码逻辑错误等）
            raise

    return str(local_path.resolve())


def load_state_dict_from_s3(
    s3_relative_path: str,
    *,
    device: str = 'cpu',
    force_download: bool = False,
):
    """
    （可选）便捷函数：在确保文件下载后，通过 torch.load 直接读入 state_dict。

    Returns:
        Any: torch.load 的返回结果
    """
    if torch is None:  # pragma: no cover - torch 仅在 inference 环境可用
        raise ImportError("torch is required to load state dicts from S3")

    local_path = ensure_weight_file(s3_relative_path, force_download=force_download)
    return torch.load(local_path, map_location=device)


__all__ = [
    "WeightFetchError",
    "ensure_weight_file",
    "load_state_dict_from_s3",
    "get_s3_client",
    "S3_BUCKET_NAME",
    "LOCAL_WEIGHTS_DIR",
]







