# 文件名: pre_post.py
# 路径: pipelines/pano/modules/teeth_attribute4/pre_post.py
"""牙齿属性4后处理模块 - 处理 YOLOv11 输出，生成属性报告"""

import numpy as np
from typing import Dict, Any, List, Tuple
import logging

logger = logging.getLogger(__name__)


def process_teeth_attributes4(
        masks: np.ndarray,
        attribute_names: List[str],
        original_shape: Tuple[int, int]
) -> Dict[str, Any]:
    """
    处理牙齿属性4分割结果，生成属性报告。

    Args:
        masks: [N, H, W] 二值掩码数组 (normalized [0,1])
        attribute_names: [N] 属性名称列表 (e.g., ['erupted'])
        original_shape: 原始图像形状 (H, W)

    Returns:
        增强的报告字典，包含属性统计、总结和保留的原始数据。
    """
    if len(masks) == 0 or len(attribute_names) == 0:
        logger.warning("No teeth attributes4 to process.")
        return {
            "attributes_detected": [],
            "attribute_counts": {},
            "summary": "未检测到牙齿属性4",
            "total_attributes": 0
        }

    # 阈值化掩码 (将 [0,1] 转为二值 0/1)
    binary_masks = (masks > 0.5).astype(np.uint8)

    # 计算每个掩码的面积 (像素计数)
    areas = np.sum(binary_masks, axis=(1, 2))

    # 构建检测到的属性列表 (带面积)
    attributes_detected = []
    for i, (name, area) in enumerate(zip(attribute_names, areas)):
        attributes_detected.append({
            "attribute": name,
            "area_pixels": int(area),
            "relative_area": float(area / (original_shape[0] * original_shape[1]))  # 相对面积百分比
        })

    # 统计计数
    attribute_counts = {}
    for attr in attribute_names:
        attribute_counts[attr] = attribute_counts.get(attr, 0) + 1

    # 生成总结
    total_attrs = len(attribute_names)
    unique_attrs = len(set(attribute_names))
    summary = f"检测到 {total_attrs} 个牙齿属性4实例，涉及 {unique_attrs} 种类型。"
    if attribute_counts:
        common_attrs = sorted(attribute_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        summary += f" 最常见: {', '.join([f'{k} ({v})' for k, v in common_attrs])}"

    logger.info(f"Processed {total_attrs} teeth attributes4 into report.")

    return {
        "attributes_detected": attributes_detected,  # 详细列表
        "attribute_counts": attribute_counts,  # {name: count}
        "summary": summary,
        "total_attributes": total_attrs,
        "binary_masks": binary_masks.tolist() if len(binary_masks) > 0 else []  # 可选: 二值掩码 (序列化)
    }