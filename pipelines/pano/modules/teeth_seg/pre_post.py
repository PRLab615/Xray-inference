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


def process_teeth_masks(masks: np.ndarray, class_names: List[str], original_shape: Tuple[int, int]) -> Dict[str, Any]:
    """
    后处理 YOLO 掩码和类名称：判断缺牙、智齿、乳牙滞留。

    Args:
        masks: [N, H, W] binary masks
        class_names: [N] class names like "tooth-11"
        original_shape: (H, W)

    Returns:
        Dict: 报告，包括每个象限牙位状态、缺牙列表、智齿列表、乳牙列表
    """
    if len(class_names) == 0:
        return {
            "report": "未检测到任何牙齿。",
            "missing_teeth": ["所有牙位缺牙"],
            "wisdom_teeth": [],
            "deciduous_teeth": [],
            "quadrant_summary": {q: 0 for q in QUADRANT_TEETH}
        }

    # 1. 解析检测类 ID
    detected_ids = set(parse_tooth_id(name) for name in class_names if parse_tooth_id(name) > 0)
    detected_classes = list(detected_ids)

    # 2. 象限缺牙判断 (仅尾号1-7)
    missing_teeth = []
    quadrant_summary = {q: 0 for q in QUADRANT_TEETH}
    for quad, teeth_ids in QUADRANT_TEETH.items():
        detected_in_quad = [tid for tid in teeth_ids if tid in detected_ids]
        quadrant_summary[quad] = len(detected_in_quad)

        # 检查1-7尾号缺牙 (忽略8智齿)
        for tid in teeth_ids[:7]:  # 1-7
            if tid not in detected_ids:
                missing_teeth.append(f"tooth-{tid} 牙位缺牙")

    # 3. 智齿判断 (尾号8)
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
        "deciduous_teeth": deciduous_teeth
        #"detected_classes": [f"tooth-{id}" for id in detected_classes]
        # "quadrant_summary": quadrant_summary,  # 每个象限检测牙数
        # 返回名称
    }