# -*- coding: utf-8 -*-
"""
侧位片34点轮廓检测模型的前处理和后处理逻辑
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional, NamedTuple

import numpy as np

if TYPE_CHECKING:
    from pipelines.ceph.modules.point_lunkuo_34.model import LandmarkResult34
else:
    LandmarkResult34 = None

logger = logging.getLogger(__name__)

# 34点轮廓点位名称列表 (P1-P34)
KEYPOINT_NAMES_34 = [f"P{i}" for i in range(1, 35)]


def preprocess_image(image_path: str, logger_instance: Optional[logging.Logger] = None) -> str:
    """
    预处理图像：验证图像文件是否存在
    """
    log = logger_instance or logger
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found for Point34 model: {image_path}")
    log.debug("Preprocessed image path: %s", image_path)
    return image_path


def postprocess_results(
    results: Any,
    image_path: str,
    weights_path: str,
    logger_instance: Optional[logging.Logger] = None,
) -> Any:
    """
    后处理 YOLO 模型输出
    """
    from pipelines.ceph.modules.point_lunkuo_34.model import LandmarkResult34

    log = logger_instance or logger
    
    if not results:
        log.warning("Empty detection results for %s", image_path)
        return LandmarkResult34({}, {}, "empty_results")

    result = results[0]
    keypoints = getattr(result, "keypoints", None)

    if keypoints is None or keypoints.xy is None or len(keypoints.xy) == 0:
        log.warning("No keypoints detected for %s", image_path)
        return LandmarkResult34({}, {}, "missing_keypoints")

    xy_tensor = keypoints.xy
    xy_tensor = xy_tensor[0] if xy_tensor.ndim == 3 else xy_tensor
    xy = xy_tensor.cpu().numpy()

    conf_tensor = getattr(keypoints, "conf", None)
    conf_arr: Optional[np.ndarray] = None
    if conf_tensor is not None:
        # 方案 A: 明确处理 2D/3D 维度
        # standard YOLO conf shape is (N, K) or (N, K, 1). We need (K,) for the first detection.
        if conf_tensor.ndim >= 2:
            conf_tensor = conf_tensor[0]
        # If it was (N, K, 1), it becomes (K, 1). We might need to squeeze it if it's not (K,)
        if conf_tensor.ndim == 2 and conf_tensor.shape[1] == 1:
            conf_tensor = conf_tensor.squeeze(1)
            
        conf_arr = conf_tensor.cpu().numpy()

    coordinates = {}
    confidences = {}

    for i, name in enumerate(KEYPOINT_NAMES_34):
        if i < len(xy):
            coordinates[name] = xy[i].tolist()
            if conf_arr is not None and i < len(conf_arr):
                confidences[name] = float(conf_arr[i])
            else:
                confidences[name] = 0.0

    return LandmarkResult34(coordinates, confidences, "success")
