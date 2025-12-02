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
from botocore.exceptions import ClientError

try:
    import torch  # 可选：供 load_state_dict_from_s3 使用
except Exception:  # pragma: no cover - 某些环境可能没有 torch
    torch = None  # type: ignore

S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL', 'http://localhost:19000')
S3_ACCESS_KEY = os.getenv('S3_ACCESS_KEY', 'root')
S3_SECRET_KEY = os.getenv('S3_SECRET_KEY', 'Sitonholy@2023')
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', 'teeth')

LOCAL_WEIGHTS_DIR = Path(os.getenv('WEIGHTS_CACHE_DIR', './cached_weights'))


class WeightFetchError(RuntimeError):
    """抛出权重下载或加载失败时的错误。"""


def _get_s3_client():
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
        client = _get_s3_client()
        try:
            client.download_file(S3_BUCKET_NAME, sanitized_key, str(local_path))
        except ClientError as exc:  # pragma: no cover - 依赖真实 S3 返回
            error_code = exc.response.get('Error', {}).get('Code')
            message = (
                f"S3 download failed (bucket={S3_BUCKET_NAME}, key={sanitized_key}, "
                f"code={error_code}): {exc}"
            )
            raise WeightFetchError(message) from exc

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
]







