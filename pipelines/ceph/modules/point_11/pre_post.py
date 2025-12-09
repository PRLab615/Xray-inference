# -*- coding: utf-8 -*-
"""
气道/腺体 11 点位模型的前处理和后处理逻辑
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import numpy as np

if TYPE_CHECKING:
    from pipelines.ceph.modules.point_11.point_11_model import LandmarkResult11
else:
    # 运行时延迟导入以避免循环依赖
    LandmarkResult11 = None  # type: ignore

logger = logging.getLogger(__name__)

# 气道/腺体 11 点位名称列表
# 参考文档：腺体气道集成与后处理说明.md
KEYPOINT_NAMES_11 = [
    "U",      # 悬雍垂尖
    "V",      # 会咽谷点
    "UPW",    # 上咽壁点
    "SPP",    # 软腭前点
    "SPPW",   # 软腭后咽壁点
    "MPW",    # 中咽壁点
    "LPW",    # 下咽壁点
    "TB",     # 舌根点
    "TPPW",   # 舌咽部后气道点
    "AD",     # 腺样体最凸点
    "Dprime", # 翼板与颅底交点 (D')
]


def preprocess_image(image_path: str, logger_instance: Optional[logging.Logger] = None) -> str:
    """
    预处理图像：验证图像文件是否存在
    
    Args:
        image_path: 图像文件路径
        logger_instance: 日志记录器（可选）
        
    Returns:
        str: 验证后的图像路径
        
    Raises:
        FileNotFoundError: 图像文件不存在
    """
    log = logger_instance or logger
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found for Point11 model: {image_path}")
    log.debug("Preprocessed image path: %s", image_path)
    return image_path


def postprocess_results(
    results: Any,
    image_path: str,
    weights_path: str,
    logger_instance: Optional[logging.Logger] = None,
) -> Any:  # 返回 LandmarkResult11，但使用 Any 避免循环导入
    """
    后处理 YOLO 模型输出，提取关键点坐标和置信度
    
    Args:
        results: YOLO 模型预测结果
        image_path: 图像路径
        weights_path: 模型权重路径
        logger_instance: 日志记录器（可选）
        
    Returns:
        LandmarkResult11: 结构化的关键点检测结果
    """
    log = logger_instance or logger
    
    if not results:
        log.warning("Empty detection results for %s", image_path)
        return create_empty_result(image_path, weights_path, status="empty_results")

    result = results[0]
    keypoints = getattr(result, "keypoints", None)

    if keypoints is None or keypoints.xy is None or len(keypoints.xy) == 0:
        log.warning("No keypoints detected for %s", image_path)
        return create_empty_result(image_path, weights_path, status="missing_keypoints")

    xy_tensor = keypoints.xy
    xy_tensor = xy_tensor[0] if xy_tensor.ndim == 3 else xy_tensor
    xy = xy_tensor.cpu().numpy()

    conf_tensor = getattr(keypoints, "conf", None)
    conf_arr: Optional[np.ndarray] = None
    if conf_tensor is not None:
        conf_tensor = conf_tensor[0] if conf_tensor.ndim == 3 else conf_tensor
        conf_arr = conf_tensor.cpu().numpy()

    coordinates: Dict[str, np.ndarray] = {}
    confidences: Dict[str, float] = {}

    for idx, name in enumerate(KEYPOINT_NAMES_11):
        if idx < xy.shape[0]:
            coordinates[name] = xy[idx]
            conf_value = (
                to_scalar(conf_arr[idx])
                if conf_arr is not None and idx < len(conf_arr)
                else 1.0
            )
        else:
            coordinates[name] = np.array([np.nan, np.nan], dtype=float)
            conf_value = 0.0
        confidences[name] = conf_value

    detected = [
        name
        for name, value in coordinates.items()
        if not (np.isnan(value[0]) or np.isnan(value[1]))
    ]
    missing = [name for name in KEYPOINT_NAMES_11 if name not in detected]

    # 延迟导入 LandmarkResult11 以避免循环依赖
    from pipelines.ceph.modules.point_11.point_11_model import LandmarkResult11  # type: ignore
    
    return LandmarkResult11(
        coordinates=coordinates,
        confidences=confidences,
        detected=detected,
        missing=missing,
        image_path=image_path,
        weights_path=weights_path,
        orig_shape=getattr(result, "orig_shape", None),
        status="ok" if detected else "no_landmarks",
    )


def create_empty_result(
    image_path: str, weights_path: str, status: str = "no_landmarks"
) -> Any:  # 返回 LandmarkResult11，但使用 Any 避免循环导入
    """
    创建空的关键点检测结果（用于错误情况）
    
    Args:
        image_path: 图像路径
        weights_path: 模型权重路径
        status: 状态描述
        
    Returns:
        LandmarkResult11: 空结果对象
    """
    # 延迟导入 LandmarkResult11 以避免循环依赖
    from pipelines.ceph.modules.point_11.point_11_model import LandmarkResult11  # type: ignore
    
    coordinates = {
        name: np.array([np.nan, np.nan], dtype=float) for name in KEYPOINT_NAMES_11
    }
    confidences = {name: 0.0 for name in KEYPOINT_NAMES_11}
    return LandmarkResult11(
        coordinates=coordinates,
        confidences=confidences,
        detected=[],
        missing=KEYPOINT_NAMES_11.copy(),
        image_path=image_path,
        weights_path=weights_path,
        orig_shape=None,
        status=status,
    )


def to_scalar(value: Any) -> float:
    """
    将数组或张量转换为 Python 标量
    
    Args:
        value: 可以是标量、数组或张量
        
    Returns:
        float: 转换后的浮点数
    """
    if isinstance(value, (int, float)):
        return float(value)
    arr = np.asarray(value, dtype=float)
    if arr.size == 0:
        return 0.0
    return float(arr.reshape(-1)[0])

