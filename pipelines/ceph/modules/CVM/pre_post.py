# -*- coding: utf-8 -*-
"""
CVM 模型的前处理和后处理逻辑
"""

import logging
import os
from collections import Counter
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

import cv2
import numpy as np

if TYPE_CHECKING:
    from pipelines.ceph.modules.CVM.cvm_model import CVMResult
else:
    # 运行时延迟导入以避免循环依赖
    CVMResult = None  # type: ignore

logger = logging.getLogger(__name__)

# CVM 模型类别定义
CVM_CLASSES = ['area', '11', '12', '21', '22', '23', '24']  # 与训练类别一致


def preprocess_image(image_path: str, logger_instance: Optional[logging.Logger] = None) -> Tuple[str, int, int]:
    """
    预处理图像：验证图像文件是否存在并读取图像尺寸
    
    Args:
        image_path: 图像文件路径
        logger_instance: 日志记录器（可选）
        
    Returns:
        Tuple[str, int, int]: (验证后的图像路径, 图像高度, 图像宽度)
        
    Raises:
        FileNotFoundError: 图像文件不存在
        ValueError: 无法读取图像
    """
    log = logger_instance or logger
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found for CVM model: {image_path}")
    
    # 读取图像以获取尺寸
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"无法读取图像: {image_path}")
    
    h, w = img.shape[:2]
    log.debug("Preprocessed image path: %s, size: %dx%d", image_path, w, h)
    return image_path, h, w


def postprocess_results(
    predictions: Any,
    image_path: str,
    weights_path: str,
    img_height: int,
    img_width: int,
    logger_instance: Optional[logging.Logger] = None,
) -> Any:  # 返回 CVMResult，但使用 Any 避免循环依赖
    """
    后处理 YOLO 模型输出，提取颈椎成熟度分期结果
    
    Args:
        predictions: YOLO 模型预测的边界框结果
        image_path: 图像路径
        weights_path: 模型权重路径
        img_height: 图像高度
        img_width: 图像宽度
        logger_instance: 日志记录器（可选）
        
    Returns:
        CVMResult: 结构化的颈椎成熟度检测结果
    """
    log = logger_instance or logger
    
    if len(predictions) == 0:
        log.warning("No detections for %s", image_path)
        return create_empty_result(image_path, weights_path, status="no_detections")
    
    # 提取所有形态标签（除area外）
    shape_tags = []
    for box in predictions:
        cls = int(box.cls[0])
        if cls != 0:  # 跳过area (类别0)
            if cls < len(CVM_CLASSES):
                shape_tags.append(CVM_CLASSES[cls])
    
    # 判断分期
    stage = get_cervical_stage(shape_tags)
    
    # 获取area边界框 (用于Coordinates)
    area_box = next((box for box in predictions if int(box.cls[0]) == 0), None)
    if not area_box:
        log.warning("未检测到area边界框 for %s", image_path)
        # 延迟导入 CVMResult 以避免循环依赖
        from pipelines.ceph.modules.CVM.cvm_model import CVMResult  # type: ignore
        return CVMResult(
            coordinates=[],
            level=stage,
            confidence=0.0,
            image_path=image_path,
            weights_path=weights_path,
            status="no_area_box",
        )
    
    # 准备坐标 (area边界框的四个顶点)
    x1, y1, x2, y2 = area_box.xyxy[0]
    coordinates = [
        [int(x1), int(y1)],  # 左上
        [int(x2), int(y1)],  # 右上
        [int(x2), int(y2)],  # 右下
        [int(x1), int(y2)]  # 左下
    ]
    
    # 计算置信度（使用所有形态标签的最高置信度）
    shape_confs = [box.conf[0] for box in predictions if int(box.cls[0]) != 0]
    confidence = float(max(shape_confs)) if shape_confs else 0.0
    
    # 延迟导入 CVMResult 以避免循环依赖
    from pipelines.ceph.modules.CVM.cvm_model import CVMResult  # type: ignore
    
    return CVMResult(
        coordinates=coordinates,
        level=stage,
        confidence=confidence,
        image_path=image_path,
        weights_path=weights_path,
        status="ok",
    )


def create_empty_result(
    image_path: str, weights_path: str, status: str = "no_detections"
) -> Any:  # 返回 CVMResult，但使用 Any 避免循环依赖
    """
    创建空的颈椎成熟度检测结果（用于错误情况）
    
    Args:
        image_path: 图像路径
        weights_path: 模型权重路径
        status: 状态描述
        
    Returns:
        CVMResult: 空结果对象
    """
    # 延迟导入 CVMResult 以避免循环依赖
    from pipelines.ceph.modules.CVM.cvm_model import CVMResult  # type: ignore
    
    return CVMResult(
        coordinates=[],
        level=0,
        confidence=0.0,
        image_path=image_path,
        weights_path=weights_path,
        status=status,
    )


def get_cervical_stage(tag_list: List[str]) -> int:
    """
    根据标签列表判断颈椎骨龄分期（不关心C2/C3/C4位置）
    
    Args:
        tag_list: 模型输出的形态标签列表（如 ['11', '21', '21']）
        
    Returns:
        CS阶段 (1-6) 或 0 (无效)
    """
    # 将标签转换为数字形式（11->1, 12->2, 21->3, 22->4, 23->5, 24->6）
    shape_map = {'11': 1, '12': 2, '21': 3, '22': 4, '23': 5, '24': 6}
    shapes = [shape_map.get(tag, 0) for tag in tag_list]
    
    # 过滤无效标签
    valid_shapes = [s for s in shapes if 1 <= s <= 6]
    
    # 无效组合（不足3个有效标签）
    if len(valid_shapes) < 3:
        return 0
    
    # 统计每个形态的数量
    count = Counter(valid_shapes)
    
    # CS1: 1个11 + 2个21
    if count.get(1, 0) == 1 and count.get(3, 0) == 2:
        return 1
    
    # CS2: 1个12 + 2个21
    if count.get(2, 0) == 1 and count.get(3, 0) == 2:
        return 2
    
    # CS3: 1个12 + 1个22 + 1个21
    if count.get(2, 0) == 1 and count.get(4, 0) == 1 and count.get(3, 0) == 1:
        return 3
    
    # CS4: 至少2个22 + 1个12
    if count.get(4, 0) >= 2 and count.get(2, 0) == 1:
        return 4
    
    # CS5: 1个12 + 1个23 + 1个22 或 1个12 + 2个23
    if (count.get(2, 0) == 1 and count.get(5, 0) == 1 and count.get(4, 0) >= 1) or \
            (count.get(2, 0) == 1 and count.get(5, 0) >= 2):
        return 5
    
    # CS6: 1个12 + 1个24 + 1个23 或 1个12 + 2个24
    if (count.get(2, 0) == 1 and count.get(6, 0) == 1 and count.get(5, 0) >= 1) or \
            (count.get(2, 0) == 1 and count.get(6, 0) >= 2):
        return 6
    
    return 0

