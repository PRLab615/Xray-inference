# 文件名: pipelines/pano/modules/teeth_detect/pre_post.py

import numpy as np
from typing import Dict, Any, List, Tuple
import logging
import re  # 用于字符串解析类名称

logger = logging.getLogger(__name__)


# 牙齿类名称映射 (假设模型输出字符串类名如 "tooth-11")
# 解析函数
def parse_tooth_id(class_name: str) -> int:
    """
    解析类名称如 "tooth-11" 到 ID 11。
    """
    match = re.search(r'tooth-(\d+)', class_name.lower())
    return int(match.group(1)) if match else 0


# 象限分组 (基于 ID)
QUADRANT_TEETH = {
    1: list(range(11, 19)),  # teeth11-18 (尾号1-8)
    2: list(range(21, 29)),  # teeth21-28
    3: list(range(31, 39)),  # teeth31-38
    4: list(range(41, 49))  # teeth41-48
}

# 乳牙类 ID (51-55,61-65)
DECIDUOUS_TEETH = [51, 52, 53, 54, 55, 61, 62, 63, 64, 65,71, 72, 73, 74, 75, 81, 82, 83, 84, 85]

# 智齿 (尾号8)
WISDOM_TEETH = [18, 28, 38, 48]


def process_teeth_masks(masks: np.ndarray, class_names: List[str], original_shape: Tuple[int, int], confidences: np.ndarray = None) -> Dict[str, Any]:
    """
    后处理 YOLO 掩码和类名称：判断缺牙、智齿、乳牙滞留。

    Args:
        masks: [N, H, W] binary masks
        class_names: [N] class names like "tooth-11"
        original_shape: (H, W)

    Returns:
        Dict: 报告，包括每个象限牙位状态、缺牙列表、智齿列表、乳牙列表、检测到的牙齿列表
    """
    if len(class_names) == 0:
        return {
            "report": "未检测到任何牙齿。",
            "missing_teeth": ["所有牙位缺牙"],
            "wisdom_teeth": [],
            "deciduous_teeth": [],
            "detected_teeth": []
        }

    # 1. 解析检测类 ID 并构建检测到的牙齿列表（带置信度去重）
    detected_teeth_raw = []
    for idx, name in enumerate(class_names):
        fdi = parse_tooth_id(name)
        if fdi > 0:
            confidence = float(confidences[idx]) if confidences is not None and idx < len(confidences) else 0.5
            detected_teeth_raw.append({
                "fdi": fdi,
                "fdi_str": str(fdi),
                "class_name": name,
                "mask_index": idx,  # 对应 masks 数组的索引
                "confidence": confidence
            })

    # 2. 去重：对同一个 FDI，保留置信度最高的检测
    fdi_to_best_detection = {}
    for detection in detected_teeth_raw:
        fdi = detection["fdi"]
        if fdi not in fdi_to_best_detection:
            fdi_to_best_detection[fdi] = detection
        else:
            # 保留置信度更高的检测
            if detection["confidence"] > fdi_to_best_detection[fdi]["confidence"]:
                fdi_to_best_detection[fdi] = detection

    # 3. 构建最终的检测结果
    detected_teeth = list(fdi_to_best_detection.values())
    detected_ids = set(detection["fdi"] for detection in detected_teeth)
    detected_classes = list(detected_ids)

    # 2. 缺牙判断 (1-7尾号 + 8尾号智齿)
    missing_teeth = []
    quadrant_summary = {q: 0 for q in QUADRANT_TEETH}
    for quad, teeth_ids in QUADRANT_TEETH.items():
        detected_in_quad = [tid for tid in teeth_ids if tid in detected_ids]
        quadrant_summary[quad] = len(detected_in_quad)

        # 检查1-7尾号缺牙
        for tid in teeth_ids[:7]:  # 1-7
            if tid not in detected_ids:
                missing_teeth.append(f"tooth-{tid} 牙位缺牙")

        # 检查8尾号智齿缺牙
        wisdom_tid = teeth_ids[7] if len(teeth_ids) > 7 else None  # 第8个是智齿
        if wisdom_tid and wisdom_tid not in detected_ids:
            missing_teeth.append(f"tooth-{wisdom_tid} 牙位缺牙")

    # 3. 智齿存在判断 (当智齿存在时记录)
    wisdom_teeth = [f"tooth-{tid} 牙位有智齿" for tid in WISDOM_TEETH if tid in detected_ids]

    # 4. 乳牙滞留判断
    deciduous_teeth = [f"tooth-{tid} 牙位乳牙滞留" for tid in DECIDUOUS_TEETH if tid in detected_ids]

    # 5. 生成报告字符串
    report_parts = []
    if missing_teeth:
        report_parts.append("缺牙情况: " + "; ".join(missing_teeth))
    if wisdom_teeth:
        report_parts.append("智齿情况: " + "; ".join(wisdom_teeth))
    if deciduous_teeth:
        report_parts.append("乳牙滞留: " + "; ".join(deciduous_teeth))


    report = "\n".join(report_parts)

    return {
        "report": report,
        "missing_teeth": missing_teeth,
        "wisdom_teeth": wisdom_teeth,
        "deciduous_teeth": deciduous_teeth,
        "detected_teeth": detected_teeth  # 新增：返回所有检测到的牙齿
    }