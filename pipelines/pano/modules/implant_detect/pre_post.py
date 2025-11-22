# 文件名: pipelines/pano/modules/implant_detect/pre_post.py

import numpy as np
import math
from typing import Dict, Any, List, Tuple
import logging

logger = logging.getLogger(__name__)

# -----------------------------------------------------------
# 1. 配置与常量
# -----------------------------------------------------------

# 类别ID到象限编号的映射 (基于 Area BBox 角点索引 0, 1, 2, 3)
# 角点索引: 0: 左上 -> Q1, 1: 右上 -> Q2, 2: 右下 -> Q3, 3: 左下 -> Q4
QUADRANT_MAP = {
    0: 1,  # 左上 -> 第一象限 (Q1)
    1: 2,  # 右上 -> 第二象限 (Q2)
    2: 3,  # 右下 -> 第三象限 (Q3)
    3: 4  # 左下 -> 第四象限 (Q4)
}


# -----------------------------------------------------------
# 2. 辅助函数
# -----------------------------------------------------------

def get_bbox_corners(bbox: List[int], img_shape: Tuple[int, int]) -> List[Tuple[int, int]]:
    """
    从 [x1, y1, x2, y2] 边界框获取四个角点坐标。
    """
    h, w = img_shape
    x1, y1, x2, y2 = bbox

    # 确保坐标在图像范围内
    x1 = max(0, min(x1, w))
    y1 = max(0, min(y1, h))
    x2 = max(0, min(x2, w))
    y2 = max(0, min(y2, h))

    corners = [
        (x1, y1),  # 0: 左上
        (x2, y1),  # 1: 右上
        (x2, y2),  # 2: 右下
        (x1, y2)  # 3: 左下
    ]
    return corners


def euclidean_distance(p1: Tuple[int, int], p2: Tuple[int, int]) -> float:
    """计算两个点之间的欧氏距离。"""
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def determine_quadrant_index(implant_corners: List[Tuple[int, int]],
                             area_corners: List[Tuple[int, int]]) -> int:
    """
    核心后处理逻辑：找到implant与area最近的角点对，并返回最近area角的索引 (0-3)。
    """
    min_global_dist = float('inf')
    closest_implant_point = None

    # 1. 找到implant与area最近的点对
    for imp_pt in implant_corners:
        for area_pt in area_corners:
            dist = euclidean_distance(imp_pt, area_pt)
            if dist < min_global_dist:
                min_global_dist = dist
                closest_implant_point = imp_pt

    if closest_implant_point is None:
        return -1

    # 2. 找到最近的 area 角索引
    min_dist_to_area_corner = float('inf')
    closest_area_corner_idx = -1

    for idx, area_pt in enumerate(area_corners):
        dist = euclidean_distance(closest_implant_point, area_pt)
        if dist < min_dist_to_area_corner:
            min_dist_to_area_corner = dist
            closest_area_corner_idx = idx

    return closest_area_corner_idx


def get_fallback_quadrant_index(implant_bbox: List[int], img_shape: Tuple[int, int]) -> int:
    """
    Fallback 逻辑：未检测到 area 时，使用 implant 中心点与图像四个角点的距离判断象限索引 (0-3)。

    Args:
        implant_bbox: [x1, y1, x2, y2]
        img_shape: (h, w)

    Returns:
        int: 最近角点索引 (0: 左上, 1: 右上, 2: 右下, 3: 左下)
    """
    h, w = img_shape
    x1, y1, x2, y2 = implant_bbox

    # 计算 implant 中心点
    x_center = (x1 + x2) / 2.0
    y_center = (y1 + y2) / 2.0
    center_point = (x_center, y_center)

    # 定义图像四个角点
    image_corners = [
        (0, 0),  # 0: 左上
        (w, 0),  # 1: 右上
        (w, h),  # 2: 右下
        (0, h)  # 3: 左下
    ]

    min_dist = float('inf')
    closest_corner_idx = -1

    # 计算中心点到四个角的距离，取最近的索引
    for idx, corner in enumerate(image_corners):
        dist = euclidean_distance(center_point, corner)
        if dist < min_dist:
            min_dist = dist
            closest_corner_idx = idx

    return closest_corner_idx


# -----------------------------------------------------------
# 3. 核心封装函数 (process_detections)
# -----------------------------------------------------------

def process_detections(
        predictions: np.ndarray,
        original_img_shape: Tuple[int, int]
) -> Dict[str, Any]:
    """
    接收 YOLO 的原始输出张量，执行 Implant/Area 分离、象限计算，并返回结构化的结果。
    """

    # 检查输入是否为空
    if predictions.size == 0 or predictions.shape[1] < 6:
        return {'implant_boxes': [], 'quadrant_counts': {1: 0, 2: 0, 3: 0, 4: 0}}

    # 1. 分离 Implant (cls=0) 和 Area (cls=1) 的边界框
    implant_bboxes_data: List[Dict[str, Any]] = []
    area_bboxes_list: List[List[int]] = []

    for pred in predictions:
        # 提取 [x1, y1, x2, y2, conf, cls]
        x1, y1, x2, y2, conf, cls = pred[:6]

        bbox = [int(x1), int(y1), int(x2), int(y2)]

        if int(cls) == 0:  # Implant
            implant_bboxes_data.append({'box': bbox, 'conf': float(conf)})
        elif int(cls) == 1:  # Area
            area_bboxes_list.append(bbox)
        # 忽略其他类别

    # 2. 检查 Area 数量
    use_fallback = not area_bboxes_list
    if use_fallback:
        logger.warning("Post-Process: 未检测到 Area 边界框 (cls=1)。使用图像四个角点作为 fallback 进行象限判断。")
    else:
        # 假设只有一个 Area，取第一个
        area_bbox = area_bboxes_list[0]
        area_corners = get_bbox_corners(area_bbox, original_img_shape)

    # 3. 遍历 Implant，计算象限
    implant_results = []
    quadrant_counts: Dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}

    for imp_data in implant_bboxes_data:
        implant_bbox = imp_data['box']
        implant_conf = imp_data['conf']

        if use_fallback:
            # Fallback: 使用中心点与图像角点距离判断
            corner_idx = get_fallback_quadrant_index(implant_bbox, original_img_shape)
        else:
            # 标准: 使用 implant 角点与 area 角点距离
            implant_corners = get_bbox_corners(implant_bbox, original_img_shape)
            corner_idx = determine_quadrant_index(implant_corners, area_corners)

        quadrant_id = QUADRANT_MAP.get(corner_idx, 0)

        # 构建 implant 结果
        implant_results.append({
            'box': implant_bbox,
            'confidence': round(implant_conf, 4),
            'quadrant': quadrant_id
        })

        # 更新计数 (只计入有效象限 1-4)
        if 1 <= quadrant_id <= 4:
            quadrant_counts[quadrant_id] += 1

    # 4. 最终输出结构
    final_output = {
        'implant_boxes': implant_results,
        'quadrant_counts': quadrant_counts
    }

    return final_output