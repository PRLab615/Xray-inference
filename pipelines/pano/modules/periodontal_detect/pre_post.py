# -*- coding: utf-8 -*-
"""
牙周吸收检测模块的前处理和后处理
整合象限截取和牙周吸收计算逻辑
"""
import cv2
import numpy as np
from typing import List, Tuple, Dict, Optional
import logging
import re

logger = logging.getLogger(__name__)

# ==================== 象限和牙齿定义 ====================
# FDI编号：每个象限的切牙、尖牙、前磨牙（序号1-5）
# 1=中切牙, 2=侧切牙, 3=尖牙, 4=第一前磨牙, 5=第二前磨牙
QUADRANT_TEETH = {
    1: [11, 12, 13, 14, 15],  # 第一象限（右上）：中切牙、侧切牙、尖牙、第一前磨牙、第二前磨牙
    2: [21, 22, 23, 24, 25],  # 第二象限（左上）
    3: [31, 32, 33, 34, 35],  # 第三象限（左下）
    4: [41, 42, 43, 44, 45],  # 第四象限（右下）
}

# 乳牙编号范围
DECIDUOUS_TOOTH_RANGES = [
    (51, 55),  # 第一象限乳牙
    (61, 65),  # 第二象限乳牙
    (71, 75),  # 第三象限乳牙
    (81, 85),  # 第四象限乳牙
]


# ==================== 工具函数 ====================
def is_deciduous_tooth(tooth_id: int) -> bool:
    """
    判断是否为乳牙
    
    Args:
        tooth_id: 牙齿编号
        
    Returns:
        如果是乳牙返回True，否则返回False
    """
    for min_id, max_id in DECIDUOUS_TOOTH_RANGES:
        if min_id <= tooth_id <= max_id:
            return True
    return False


def extract_tooth_id_from_label(label: str) -> Optional[int]:
    """
    从标签中提取牙齿编号
    
    Args:
        label: 标签字符串，如 "tooth-11", "11", "tooth_11" 等
        
    Returns:
        牙齿编号，如果无法提取则返回None
    """
    match = re.search(r'(\d+)', label)
    if match:
        return int(match.group(1))
    return None


def get_quadrant_for_tooth(tooth_id: int) -> Optional[int]:
    """
    根据FDI编号获取象限
    
    Args:
        tooth_id: FDI牙齿编号
        
    Returns:
        象限编号（1-4），如果不在范围内返回None
    """
    if 11 <= tooth_id <= 18:
        return 1
    elif 21 <= tooth_id <= 28:
        return 2
    elif 31 <= tooth_id <= 38:
        return 3
    elif 41 <= tooth_id <= 48:
        return 4
    return None


def check_deciduous_teeth_in_quadrant(labels: List[str], quadrant: int) -> bool:
    """
    检查指定象限是否包含乳牙
    
    Args:
        labels: 所有牙齿的标签列表
        quadrant: 象限编号 (1-4)
        
    Returns:
        如果包含乳牙返回True，否则返回False
    """
    # 确定该象限对应的乳牙范围
    if quadrant == 1:
        deciduous_range = (51, 55)
    elif quadrant == 2:
        deciduous_range = (61, 65)
    elif quadrant == 3:
        deciduous_range = (71, 75)
    elif quadrant == 4:
        deciduous_range = (81, 85)
    else:
        return False
    
    min_deciduous, max_deciduous = deciduous_range
    
    # 检查标签中是否有乳牙编号
    for label in labels:
        tooth_id = extract_tooth_id_from_label(label)
        if tooth_id is not None:
            if min_deciduous <= tooth_id <= max_deciduous:
                return True
    
    return False


# ==================== 前处理：象限截取 ====================
def extract_quadrant_crop(
    image: np.ndarray,
    masks: List[np.ndarray],
    labels: List[str],
    quadrant: int
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], List[int]]:
    """
    从全景片中截取指定象限的矩形区域，包含切牙、尖牙、前磨牙（序号1-5）
    即使没有牙齿也要包含进去，确保存在的牙齿mask都在矩形框里面，并进行上下扩充30个像素
    
    Args:
        image: 原始全景片图像 (H, W, 3)
        masks: 所有牙齿的mask列表，每个mask为 (H, W) 的二进制数组
        labels: 对应的标签列表，如 ["tooth-11", "tooth-12", ...]
        quadrant: 象限编号 (1-4)
        
    Returns:
        (crop_image, crop_mask, tooth_ids): 
        - crop_image: 截取的矩形图像，即使该象限没有牙齿也会返回一个合理的区域
        - crop_mask: 合并后的mask，如果没有牙齿则为全零mask
        - tooth_ids: 该象限内实际存在的牙齿编号列表（按顺序，缺牙跳过）
    """
    if quadrant not in QUADRANT_TEETH:
        return None, None, []
    
    target_teeth = QUADRANT_TEETH[quadrant]  # 该象限需要的5颗牙齿编号
    h, w = image.shape[:2]
    
    # 创建标签到mask的映射
    label_to_mask = {}
    for mask, label in zip(masks, labels):
        tooth_id = extract_tooth_id_from_label(label)
        if tooth_id is not None:
            label_to_mask[tooth_id] = mask
    
    # 找到该象限内实际存在的牙齿（只取目标5颗牙，缺牙跳过）
    quadrant_masks = []
    quadrant_tooth_ids = []
    quadrant_bboxes = []
    
    for tooth_id in target_teeth:
        if tooth_id not in label_to_mask:
            continue  # 缺牙，跳过
        
        mask = label_to_mask[tooth_id]
        
        # 计算该mask的bbox
        rows = np.any(mask, axis=1)
        cols = np.any(mask, axis=0)
        if not np.any(rows) or not np.any(cols):
            continue  # mask无效，跳过
        
        y_min, y_max = np.where(rows)[0][[0, -1]]
        x_min, x_max = np.where(cols)[0][[0, -1]]
        
        # 检查bbox是否有效
        if x_max <= x_min or y_max <= y_min:
            continue
        
        quadrant_masks.append(mask)
        quadrant_tooth_ids.append(tooth_id)
        quadrant_bboxes.append((x_min, y_min, x_max, y_max))
    
    # 根据实际存在的牙齿mask位置确定矩形框
    # 使用最上、最下、最左、最右的点来确定矩形框，上下扩充30个像素
    vertical_expand = 30  # 上下扩充30个像素
    
    if quadrant_bboxes:
        # 有牙齿存在：根据所有牙齿mask的边界点确定矩形框
        # 找到最左、最右、最上、最下的点
        x_mins, y_mins, x_maxs, y_maxs = zip(*quadrant_bboxes)
        crop_x1 = min(x_mins)  # 最左的点
        crop_x2 = max(x_maxs)  # 最右的点
        crop_y1 = min(y_mins)  # 最上的点
        crop_y2 = max(y_maxs)  # 最下的点
        
        # 上下扩充30个像素
        crop_y1 = max(0, crop_y1 - vertical_expand)
        crop_y2 = min(h, crop_y2 + vertical_expand)
        
        # 确保左右边界在图像范围内
        crop_x1 = max(0, crop_x1)
        crop_x2 = min(w, crop_x2)
    else:
        # 没有牙齿：根据象限位置推断一个合理的区域
        # 将图像按象限划分，每个象限占据图像的一部分
        if quadrant == 1:  # 右上
            crop_x1 = w // 2
            crop_x2 = w
            crop_y1 = 0
            crop_y2 = h // 2
        elif quadrant == 2:  # 左上
            crop_x1 = 0
            crop_x2 = w // 2
            crop_y1 = 0
            crop_y2 = h // 2
        elif quadrant == 3:  # 左下
            crop_x1 = 0
            crop_x2 = w // 2
            crop_y1 = h // 2
            crop_y2 = h
        else:  # 右下
            crop_x1 = w // 2
            crop_x2 = w
            crop_y1 = h // 2
            crop_y2 = h
        
        # 上下扩充30个像素
        crop_y1 = max(0, crop_y1 - vertical_expand)
        crop_y2 = min(h, crop_y2 + vertical_expand)
    
    # 确保截取区域有效
    if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
        return None, None, []
    
    # 截取图像
    crop_image = image[crop_y1:crop_y2, crop_x1:crop_x2].copy()
    crop_h, crop_w = crop_image.shape[:2]
    
    # 合并该象限的所有mask并调整坐标
    crop_mask = np.zeros((crop_h, crop_w), dtype=np.uint8)
    for mask in quadrant_masks:
        # mask已经在process_panoramic_segmentation中resize到原始图像尺寸并转换为二进制
        # 直接截取mask（crop_y1, crop_y2, crop_x1, crop_x2已经在有效范围内）
        mask_crop = mask[crop_y1:crop_y2, crop_x1:crop_x2]
        
        # 合并到crop_mask
        crop_mask = np.maximum(crop_mask, mask_crop)
    
    return crop_image, crop_mask, quadrant_tooth_ids


def process_panoramic_segmentation(
    image: np.ndarray,
    masks: np.ndarray,
    labels: List[str],
    original_shape: Tuple[int, int]
) -> Dict[int, Tuple[Optional[np.ndarray], Optional[np.ndarray], List[int], bool]]:
    """
    处理全景片分割结果，按象限截取
    
    Args:
        image: 原始全景片图像
        masks: 牙齿分割mask数组，shape (N, H, W)
        labels: 对应的标签列表，如 ["tooth-11", "tooth-12", ...]
        original_shape: 原始图像尺寸 (H, W)
        
    Returns:
        dict: {象限编号: (crop_image, crop_mask, tooth_ids, has_deciduous)}
        has_deciduous: 该象限是否包含乳牙
    """
    img_h, img_w = image.shape[:2]
    
    # 处理masks：转换为二进制格式并resize到原始图像尺寸
    processed_masks = []
    for idx in range(len(masks)):
        mask = masks[idx]
        
        # 将mask转换为二进制格式
        if mask.dtype != np.uint8:
            mask = (mask > 0.5).astype(np.uint8)
        else:
            mask = (mask > 0).astype(np.uint8)
        
        # 如果mask尺寸与原始图像不一致，需要resize到原始图像尺寸
        mask_h, mask_w = mask.shape
        if mask_h != img_h or mask_w != img_w:
            # 使用INTER_NEAREST保持二进制特性
            mask = cv2.resize(mask, (img_w, img_h), interpolation=cv2.INTER_NEAREST)
        
        processed_masks.append(mask)
    
    # 按象限截取
    quadrant_results = {}
    for quadrant in [1, 2, 3, 4]:
        # 检查是否包含乳牙
        has_deciduous = check_deciduous_teeth_in_quadrant(labels, quadrant)
        
        if has_deciduous:
            # 如果包含乳牙，不进行截取，返回None但标记有乳牙
            quadrant_results[quadrant] = (None, None, [], True)
        else:
            # 正常截取（使用原始高分辨率图像）
            crop_img, crop_mask, tooth_ids = extract_quadrant_crop(
                image, processed_masks, labels, quadrant
            )
            if crop_img is not None:
                quadrant_results[quadrant] = (crop_img, crop_mask, tooth_ids, False)
            else:
                quadrant_results[quadrant] = (None, None, [], False)
    
    return quadrant_results


# ==================== 后处理：牙周吸收计算 ====================
def calculate_distance(point1: Tuple[float, float], point2: Tuple[float, float]) -> float:
    """
    计算两点之间的欧氏距离
    
    Args:
        point1: (x, y) 坐标
        point2: (x, y) 坐标
        
    Returns:
        距离值
    """
    return np.sqrt((point1[0] - point2[0]) ** 2 + (point1[1] - point2[1]) ** 2)


def calculate_absorption_ratio(
    cej_point: Tuple[float, float],
    apex_point: Tuple[float, float],
    boneline_point: Tuple[float, float]
) -> Optional[float]:
    """
    计算牙周吸收比例：CEJ到BoneLine的距离 / CEJ到Apex的距离
    
    Args:
        cej_point: CEJ关键点坐标 (x, y)
        apex_point: Apex关键点坐标 (x, y)
        boneline_point: BoneLine关键点坐标 (x, y)
        
    Returns:
        吸收比例，如果计算失败返回None
    """
    if cej_point is None or apex_point is None or boneline_point is None:
        return None
    
    # 检查坐标是否有效
    if any(coord is None or np.isnan(coord) for coord in cej_point + apex_point + boneline_point):
        return None
    
    distance_cej_boneline = calculate_distance(cej_point, boneline_point)
    distance_cej_apex = calculate_distance(cej_point, apex_point)
    
    if distance_cej_apex == 0:
        return None
    
    ratio = distance_cej_boneline / distance_cej_apex
    return ratio


def classify_absorption_severity(ratio: float) -> str:
    """
    根据吸收比例分类牙周吸收严重程度
    
    Args:
        ratio: 吸收比例（CEJ到BoneLine的距离 / CEJ到Apex的距离）
        
    Returns:
        严重程度描述："轻度"、"中度"、"重度" 或 "正常"
    """
    if ratio < 0.15:
        return "正常"
    elif ratio < 1.0 / 3.0:
        return "轻度"
    elif ratio < 2.0 / 3.0:
        return "中度"
    else:
        return "重度"


def process_keypoints_for_absorption(
    keypoints_xy: np.ndarray,
    keypoints_conf: np.ndarray,
    tooth_id: int
) -> Optional[Dict]:
    """
    处理关键点数据，计算牙周吸收
    
    Args:
        keypoints_xy: 关键点坐标数组，shape (3, 2)，顺序为 [CEJ, Apex, BoneLine]
        keypoints_conf: 关键点置信度数组，shape (3,)
        tooth_id: 牙齿编号
        
    Returns:
        包含吸收分析结果的字典，如果关键点无效返回None
    """
    if keypoints_xy is None or len(keypoints_xy) < 3:
        return None
    
    # 检查置信度阈值（至少0.3才认为有效）
    if keypoints_conf is not None:
        if any(conf < 0.3 for conf in keypoints_conf[:3]):
            return None
    
    # 提取三个关键点
    cej_point = (float(keypoints_xy[0][0]), float(keypoints_xy[0][1]))
    apex_point = (float(keypoints_xy[1][0]), float(keypoints_xy[1][1]))
    boneline_point = (float(keypoints_xy[2][0]), float(keypoints_xy[2][1]))
    
    # 计算吸收比例
    ratio = calculate_absorption_ratio(cej_point, apex_point, boneline_point)
    if ratio is None:
        return None
    
    # 分类严重程度
    severity = classify_absorption_severity(ratio)
    
    # 计算置信度：取三个关键点置信度的平均值
    confidence = 0.0
    if keypoints_conf is not None and len(keypoints_conf) >= 3:
        confidence = float(np.mean(keypoints_conf[:3]))
    else:
        confidence = 0.5  # 默认值
    
    return {
        "tooth_id": tooth_id,
        "cej_point": cej_point,
        "apex_point": apex_point,
        "boneline_point": boneline_point,
        "absorption_ratio": ratio,
        "severity": severity,
        "confidence": confidence,
        "distance_cej_boneline": calculate_distance(cej_point, boneline_point),
        "distance_cej_apex": calculate_distance(cej_point, apex_point),
    }


def analyze_absorption(
    pose_results,
    tooth_ids: List[int]
) -> List[Dict]:
    """
    分析牙周吸收
    
    Args:
        pose_results: 关键点检测结果（YOLO Results对象）
        tooth_ids: 该象限内的牙齿编号列表
        
    Returns:
        分析结果列表，每个元素包含牙齿编号和吸收程度
    """
    result = pose_results[0]
    absorption_results = []
    
    if result.keypoints is None or result.keypoints.xy is None:
        return absorption_results
    
    num_detections = len(result.boxes)
    num_tooth_ids = len(tooth_ids)
    
    # 假设检测到的牙齿数量应该与tooth_ids数量匹配
    # 如果数量不匹配，按顺序对应
    for idx in range(min(num_detections, num_tooth_ids)):
        tooth_id = tooth_ids[idx] if idx < num_tooth_ids else None
        if tooth_id is None:
            continue
        
        if idx >= len(result.keypoints.xy):
            continue
        
        keypoints_xy = result.keypoints.xy[idx].cpu().numpy()
        keypoints_conf = None
        if result.keypoints.conf is not None:
            keypoints_conf = result.keypoints.conf[idx].cpu().numpy()
        
        # 检查关键点数量（应该是3个：CEJ, Apex, BoneLine）
        if len(keypoints_xy) < 3:
            continue
        
        analysis = process_keypoints_for_absorption(
            keypoints_xy,
            keypoints_conf,
            tooth_id
        )
        
        if analysis is not None:
            absorption_results.append(analysis)
    
    return absorption_results

