# 文件名: pipelines/pano/modules/rootTipDensity_detect/pre_post.py

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


def determine_quadrant_index(density_corners: List[Tuple[int, int]],
                             area_corners: List[Tuple[int, int]]) -> int:
    """
    核心后处理逻辑：找到低密度影与area最近的角点对，并返回最近area角的索引 (0-3)。
    """
    min_global_dist = float('inf')
    closest_density_point = None

    # 1. 找到低密度影与area最近的点对
    for density_pt in density_corners:
        for area_pt in area_corners:
            dist = euclidean_distance(density_pt, area_pt)
            if dist < min_global_dist:
                min_global_dist = dist
                closest_density_point = density_pt

    if closest_density_point is None:
        return -1

    # 2. 找到最近的 area 角索引
    min_dist_to_area_corner = float('inf')
    closest_area_corner_idx = -1

    for idx, area_pt in enumerate(area_corners):
        dist = euclidean_distance(closest_density_point, area_pt)
        if dist < min_dist_to_area_corner:
            min_dist_to_area_corner = dist
            closest_area_corner_idx = idx

    return closest_area_corner_idx


def compute_containment_ratio(inner_box: List[int], outer_box: List[int]) -> float:
    """
    计算 inner_box 被 outer_box 包含的比例。
    返回值范围 [0, 1]，1 表示完全包含。
    """
    x1_i, y1_i, x2_i, y2_i = inner_box
    x1_o, y1_o, x2_o, y2_o = outer_box
    
    # 计算交集
    inter_x1 = max(x1_i, x1_o)
    inter_y1 = max(y1_i, y1_o)
    inter_x2 = min(x2_i, x2_o)
    inter_y2 = min(y2_i, y2_o)
    
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0
    
    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    inner_area = (x2_i - x1_i) * (y2_i - y1_i)
    
    if inner_area <= 0:
        return 0.0
    
    return inter_area / inner_area


def filter_contained_boxes(bboxes_data: List[Dict[str, Any]], containment_threshold: float = 0.8) -> List[Dict[str, Any]]:
    """
    过滤被其他框大部分包含的框，保留置信度高的。
    
    Args:
        bboxes_data: [{'box': [x1,y1,x2,y2], 'conf': float}, ...]
        containment_threshold: 包含比例阈值，超过此值认为是重复检测
    
    Returns:
        过滤后的框列表
    """
    if len(bboxes_data) <= 1:
        return bboxes_data
    
    # 按置信度降序排序
    sorted_data = sorted(bboxes_data, key=lambda x: x['conf'], reverse=True)
    keep = [True] * len(sorted_data)
    
    for i in range(len(sorted_data)):
        if not keep[i]:
            continue
        box_i = sorted_data[i]['box']
        
        for j in range(i + 1, len(sorted_data)):
            if not keep[j]:
                continue
            box_j = sorted_data[j]['box']
            
            # 检查 j 是否被 i 大部分包含（i 置信度更高）
            containment = compute_containment_ratio(box_j, box_i)
            if containment >= containment_threshold:
                keep[j] = False
                logger.debug(f"Filtered box {j} (conf={sorted_data[j]['conf']:.3f}) "
                           f"contained by box {i} (conf={sorted_data[i]['conf']:.3f}), "
                           f"containment={containment:.2f}")
    
    return [sorted_data[i] for i in range(len(sorted_data)) if keep[i]]


def get_fallback_quadrant_index(density_bbox: List[int], img_shape: Tuple[int, int]) -> int:
    """
    Fallback 逻辑：未检测到 area 时，使用低密度影中心点与图像四个角点的距离判断象限索引 (0-3)。

    Args:
        density_bbox: [x1, y1, x2, y2]
        img_shape: (h, w)

    Returns:
        int: 最近角点索引 (0: 左上, 1: 右上, 2: 右下, 3: 左下)
    """
    h, w = img_shape
    x1, y1, x2, y2 = density_bbox

    # 计算低密度影中心点
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
    接收 YOLO 的原始输出张量，执行低密度影/Area 分离、象限计算，并返回结构化的结果。
    
    Args:
        predictions: YOLO 输出的检测结果，格式为 [N, 6]，每行为 [x1, y1, x2, y2, conf, cls]
        original_img_shape: 原始图像尺寸 (H, W)
    
    Returns:
        dict: {
            "density_boxes": [{"box": [x1, y1, x2, y2], "confidence": float, "quadrant": int}, ...],
            "quadrant_counts": {1: int, 2: int, 3: int, 4: int}
        }
    """

    # 检查输入是否为空
    if predictions.size == 0 or predictions.shape[1] < 6:
        return {'density_boxes': [], 'quadrant_counts': {1: 0, 2: 0, 3: 0, 4: 0}}

    # 1. 分离低密度影 (cls=0) 和 Area (cls=1) 的边界框
    density_bboxes_data: List[Dict[str, Any]] = []
    area_bboxes_list: List[List[int]] = []

    for pred in predictions:
        # 提取 [x1, y1, x2, y2, conf, cls]
        x1, y1, x2, y2, conf, cls = pred[:6]

        bbox = [int(x1), int(y1), int(x2), int(y2)]

        if int(cls) == 0:  # Low_Density_Lesion
            density_bboxes_data.append({'box': bbox, 'conf': float(conf)})
        elif int(cls) == 1:  # Area
            area_bboxes_list.append(bbox)
        # 忽略其他类别

    # 2. 过滤大框包小框的重复检测（保留高置信度的）
    density_bboxes_data = filter_contained_boxes(density_bboxes_data, containment_threshold=0.7)

    # 3. 检查 Area 数量
    use_fallback = not area_bboxes_list
    if use_fallback:
        logger.warning("Post-Process: 未检测到 Area 边界框 (cls=1)。使用图像四个角点作为 fallback 进行象限判断。")
    else:
        # 假设只有一个 Area，取第一个
        area_bbox = area_bboxes_list[0]
        area_corners = get_bbox_corners(area_bbox, original_img_shape)

    # 4. 遍历低密度影，计算象限
    density_results = []
    quadrant_counts: Dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}

    for density_data in density_bboxes_data:
        density_bbox = density_data['box']
        density_conf = density_data['conf']

        if use_fallback:
            # Fallback: 使用中心点与图像角点距离判断
            corner_idx = get_fallback_quadrant_index(density_bbox, original_img_shape)
        else:
            # 标准: 使用低密度影角点与 area 角点距离
            density_corners = get_bbox_corners(density_bbox, original_img_shape)
            corner_idx = determine_quadrant_index(density_corners, area_corners)

        quadrant_id = QUADRANT_MAP.get(corner_idx, 0)

        # 构建低密度影结果
        density_results.append({
            'box': density_bbox,
            'confidence': round(density_conf, 4),
            'quadrant': quadrant_id
        })

        # 更新计数 (只计入有效象限 1-4)
        if 1 <= quadrant_id <= 4:
            quadrant_counts[quadrant_id] += 1

    # 5. 最终输出结构
    final_output = {
        'density_boxes': density_results,
        'quadrant_counts': quadrant_counts
    }

    return final_output

