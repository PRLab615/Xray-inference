# -*- coding: utf-8 -*-
"""
全景片重算模块：基于修改后的基础几何数据重新计算所有衍生数据。

因果关系说明：
    "因"字段（透传，客户端可修改）：
        - Metadata
        - AnatomyResults[*].SegmentationMask（髁突/下颌升支/上颌窦的多边形坐标）
        - MaxillarySinus[*].Inflammation（炎症判断，模型直推）
        - MaxillarySinus[*].TypeClassification（上颌窦分型，模型直推）
        - ToothAnalysis[*].FDI, SegmentationMask, Properties, Confidence
        - JointAndMandible.CondyleAssessment.*.Morphology（髁突形态分类）
        - ImplantAnalysis.Items[*].BBox, Confidence
        - ThirdMolarSummary[*].Impactions（智齿阻生状态，模型直推）
        - PeriodontalCondition（牙周吸收检测，模型直推）
        - RootTipDensityAnalysis.Items[*]
    
    "果"字段（服务端重算）：
        - CondyleAssessment.OverallSymmetry（髁突对称性）
        - RamusSymmetry, GonialAngleSymmetry（下颌升支/下颌角对称性）
        - MaxillarySinus[*].Pneumatization（上颌窦气化）
        - MaxillarySinus[*].RootEntryToothFDI（牙根进入上颌窦）
        - MissingTeeth（缺牙推导）
        - ThirdMolarSummary[*].Level（智齿Level）
        - ImplantAnalysis.TotalCount, QuadrantCounts
        - RootTipDensityAnalysis.TotalCount, QuadrantCounts
        - 所有 Detail 字段
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from .pano_report_utils import (
    MORPHOLOGY_MAP,
    QUADRANT_MAP,
    WISDOM_TEETH_FDI,
    DECIDUOUS_TEETH_FDI,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 1. 主入口函数
# =============================================================================

def recalculate_pano_report(
    input_data: Dict[str, Any],
    pixel_spacing: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    基于客户端修改后的数据重新计算全景片报告。
    
    Args:
        input_data: 客户端传入的完整推理结果 JSON（example_pano_result.json 格式）
        pixel_spacing: 由 API 层解析后的比例尺信息（可选）
            格式: {"scale_x": float, "scale_y": float, "source": str}
            如果为 None，则从 input_data.ImageSpacing 获取
    
    Returns:
        重算后的完整报告 JSON
    """
    # ========== 1. 提取并透传"因"字段 ==========
    metadata = input_data.get("Metadata", {})
    
    # 构建 ImageSpacing：优先使用传入的 pixel_spacing，否则从 input_data 获取
    if pixel_spacing and pixel_spacing.get("scale_x"):
        image_spacing = {
            "X": pixel_spacing["scale_x"],
            "Y": pixel_spacing.get("scale_y", pixel_spacing["scale_x"]),
            "Unit": "mm/pixel",
        }
        logger.info(
            f"[Pano Recalculate] Using pixel_spacing from API: "
            f"X={image_spacing['X']:.4f}, Y={image_spacing['Y']:.4f} mm/pixel, "
            f"source={pixel_spacing.get('source', 'unknown')}"
        )
    else:
        # 从 input_data 获取（兼容直接调用的场景）
        image_spacing = input_data.get("ImageSpacing")
        if not image_spacing or not image_spacing.get("X"):
            raise ValueError(
                "[PixelSpacing] Neither pixel_spacing parameter nor input_data.ImageSpacing is valid. "
                "Please provide pixel_spacing or ensure input_data contains valid ImageSpacing."
            )
        logger.info(
            f"[Pano Recalculate] Using ImageSpacing from input_data: "
            f"X={image_spacing['X']:.4f}, Y={image_spacing['Y']:.4f} mm/pixel"
        )
    anatomy_results = input_data.get("AnatomyResults", [])
    periodontal_condition = input_data.get("PeriodontalCondition", {})
    
    # 1.1 提取 JointAndMandible 中的"因"字段（Morphology）
    joint_mandible = input_data.get("JointAndMandible", {})
    condyle_assessment = joint_mandible.get("CondyleAssessment", {})
    left_morphology = condyle_assessment.get("condyle_Left", {}).get("Morphology", 0)
    right_morphology = condyle_assessment.get("condyle_Right", {}).get("Morphology", 0)
    left_confidence = condyle_assessment.get("condyle_Left", {}).get("Confidence", 0.0)
    right_confidence = condyle_assessment.get("condyle_Right", {}).get("Confidence", 0.0)
    
    # 1.2 提取 MaxillarySinus 中的"因"字段（Inflammation, TypeClassification）
    maxillary_sinus_input = input_data.get("MaxillarySinus", [])
    
    # 1.3 提取 ToothAnalysis（全部透传）
    tooth_analysis = input_data.get("ToothAnalysis", [])
    
    # 1.4 提取 ThirdMolarSummary 中的"因"字段（Impactions）
    third_molar_summary_input = input_data.get("ThirdMolarSummary", {})
    
    # 1.5 提取 ImplantAnalysis.Items（透传 BBox, Confidence）
    implant_analysis_input = input_data.get("ImplantAnalysis", {})
    implant_items = implant_analysis_input.get("Items", [])
    
    # 1.6 提取 RootTipDensityAnalysis.Items（透传）
    root_tip_density_input = input_data.get("RootTipDensityAnalysis", {})
    density_items = root_tip_density_input.get("Items", [])
    
    # ========== 2. 重新计算"果"字段 ==========
    
    # 2.1 从 AnatomyResults 提取 mask 信息
    anatomy_masks = _parse_anatomy_results(anatomy_results)
    
    # 2.2 重算 CondyleAssessment（对称性）
    condyle_assessment_result = _recalculate_condyle_assessment(
        left_morphology=left_morphology,
        right_morphology=right_morphology,
        left_confidence=left_confidence,
        right_confidence=right_confidence,
        anatomy_masks=anatomy_masks,
    )
    
    # 2.3 重算 RamusSymmetry, GonialAngleSymmetry, Detail
    ramus_result = _recalculate_ramus_symmetry(anatomy_masks)
    
    # 2.4 重算 MaxillarySinus（Pneumatization, RootEntryToothFDI, Detail）
    maxillary_sinus_result = _recalculate_maxillary_sinus(
        maxillary_sinus_input=maxillary_sinus_input,
        anatomy_masks=anatomy_masks,
        tooth_analysis=tooth_analysis,
    )
    
    # 2.5 重算 MissingTeeth（从检测到的牙齿列表反推）
    missing_teeth_result = _recalculate_missing_teeth(tooth_analysis)
    
    # 2.6 重算 ThirdMolarSummary（Level, Detail）
    third_molar_summary_result = _recalculate_third_molar_summary(
        third_molar_summary_input=third_molar_summary_input,
        tooth_analysis=tooth_analysis,
    )
    
    # 2.7 重算 ImplantAnalysis（TotalCount, QuadrantCounts, Detail）
    implant_analysis_result = _recalculate_implant_analysis(implant_items)
    
    # 2.8 重算 RootTipDensityAnalysis（TotalCount, QuadrantCounts, Detail）
    root_tip_density_result = _recalculate_root_tip_density(density_items)
    
    # ========== 3. 组装输出 JSON ==========
    output_data = {
        "Metadata": metadata,
        "ImageSpacing": image_spacing,
        "AnatomyResults": anatomy_results,  # 透传
        "JointAndMandible": {
            "CondyleAssessment": condyle_assessment_result,
            "RamusSymmetry": ramus_result["RamusSymmetry"],
            "GonialAngleSymmetry": ramus_result["GonialAngleSymmetry"],
            "Detail": ramus_result["Detail"],
            "Confidence": ramus_result["Confidence"],
        },
        "MaxillarySinus": maxillary_sinus_result,
        "PeriodontalCondition": periodontal_condition,  # 透传
        "MissingTeeth": missing_teeth_result,
        "ThirdMolarSummary": third_molar_summary_result,
        "ImplantAnalysis": implant_analysis_result,
        "RootTipDensityAnalysis": root_tip_density_result,
        "ToothAnalysis": tooth_analysis,  # 透传
    }
    
    logger.info(
        "[Pano Recalculate] Generated report: %d teeth, %d missing, %d implants, %d density items",
        len(tooth_analysis),
        len(missing_teeth_result),
        implant_analysis_result.get("TotalCount", 0),
        root_tip_density_result.get("TotalCount", 0),
    )
    
    return output_data


# =============================================================================
# 2. 辅助函数：解析 AnatomyResults
# =============================================================================

def _parse_anatomy_results(anatomy_results: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    解析 AnatomyResults，提取各解剖结构的 mask 信息。
    
    Args:
        anatomy_results: AnatomyResults 列表
    
    Returns:
        字典：{label: {coordinates: [...], confidence: float}}
    """
    masks = {}
    for item in anatomy_results:
        label = item.get("Label", "")
        confidence = item.get("Confidence", 0.0)
        seg_mask = item.get("SegmentationMask", {})
        coordinates = seg_mask.get("Coordinates", [])
        
        masks[label] = {
            "coordinates": coordinates,
            "confidence": confidence,
        }
    
    return masks


# =============================================================================
# 3. 重算函数：髁突评估
# =============================================================================

def _recalculate_condyle_assessment(
    left_morphology: int,
    right_morphology: int,
    left_confidence: float,
    right_confidence: float,
    anatomy_masks: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    重算 CondyleAssessment。
    
    "因"：Morphology, Confidence（透传）
    "果"：OverallSymmetry, Detail（重算）
    
    Args:
        left_morphology: 左侧髁突形态分类 (0=正常, 1=吸收, 2=疑似)
        right_morphology: 右侧髁突形态分类
        left_confidence: 左侧置信度
        right_confidence: 右侧置信度
        anatomy_masks: 解析后的 AnatomyResults
    
    Returns:
        重算后的 CondyleAssessment
    """
    # 生成 Detail（根据 Morphology）
    left_detail = MORPHOLOGY_MAP.get(left_morphology, MORPHOLOGY_MAP[0])["detail"]
    right_detail = MORPHOLOGY_MAP.get(right_morphology, MORPHOLOGY_MAP[0])["detail"]
    
    # 计算对称性（根据左右髁突 mask 面积）
    overall_symmetry = _calculate_condyle_symmetry(anatomy_masks)
    
    # 综合置信度
    confidence_overall = max(left_confidence, right_confidence)
    
    return {
        "condyle_Left": {
            "Morphology": left_morphology,
            "Detail": left_detail,
            "Confidence": round(float(left_confidence), 2),
        },
        "condyle_Right": {
            "Morphology": right_morphology,
            "Detail": right_detail,
            "Confidence": round(float(right_confidence), 2),
        },
        "OverallSymmetry": overall_symmetry,
        "Confidence_Overall": round(float(confidence_overall), 2),
    }


def _calculate_condyle_symmetry(anatomy_masks: Dict[str, Dict[str, Any]]) -> int:
    """
    根据左右髁突 mask 面积计算对称性。
    
    Returns:
        0=对称, 1=左侧大, 2=右侧大
    """
    left_coords = anatomy_masks.get("condyle_left", {}).get("coordinates", [])
    right_coords = anatomy_masks.get("condyle_right", {}).get("coordinates", [])
    
    # 计算多边形面积
    left_area = _calculate_polygon_area(left_coords)
    right_area = _calculate_polygon_area(right_coords)
    
    # 如果两侧面积差异超过 15%，则认为不对称
    if left_area == 0 and right_area == 0:
        return 0  # 无数据，默认对称
    
    total = left_area + right_area
    if total == 0:
        return 0
    
    diff_ratio = abs(left_area - right_area) / max(left_area, right_area) if max(left_area, right_area) > 0 else 0
    
    if diff_ratio <= 0.15:
        return 0  # 对称
    elif left_area > right_area:
        return 1  # 左侧大
    else:
        return 2  # 右侧大


def _calculate_polygon_area(coordinates: List[List[float]]) -> float:
    """
    使用 Shoelace 公式计算多边形面积。
    
    Args:
        coordinates: [[x1, y1], [x2, y2], ...] 多边形坐标点
    
    Returns:
        面积（像素平方）
    """
    if not coordinates or len(coordinates) < 3:
        return 0.0
    
    n = len(coordinates)
    area = 0.0
    
    for i in range(n):
        j = (i + 1) % n
        try:
            x_i, y_i = float(coordinates[i][0]), float(coordinates[i][1])
            x_j, y_j = float(coordinates[j][0]), float(coordinates[j][1])
            area += x_i * y_j
            area -= x_j * y_i
        except (IndexError, TypeError, ValueError):
            continue
    
    return abs(area) / 2.0


# =============================================================================
# 4. 重算函数：下颌升支对称性
# =============================================================================

def _recalculate_ramus_symmetry(
    anatomy_masks: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    重算 RamusSymmetry 和 GonialAngleSymmetry。
    
    Args:
        anatomy_masks: 解析后的 AnatomyResults
    
    Returns:
        {RamusSymmetry: bool, GonialAngleSymmetry: bool, Detail: str, Confidence: float}
    """
    left_coords = anatomy_masks.get("mandible_left", {}).get("coordinates", [])
    right_coords = anatomy_masks.get("mandible_right", {}).get("coordinates", [])
    
    left_confidence = anatomy_masks.get("mandible_left", {}).get("confidence", 0.0)
    right_confidence = anatomy_masks.get("mandible_right", {}).get("confidence", 0.0)
    
    # 计算升支高度（使用 bounding box 高度近似）
    left_height = _calculate_bounding_height(left_coords)
    right_height = _calculate_bounding_height(right_coords)
    
    # 判断对称性：高度差异小于 10% 认为对称
    if left_height == 0 and right_height == 0:
        ramus_symmetric = True  # 无数据，默认对称
    elif max(left_height, right_height) > 0:
        height_diff_ratio = abs(left_height - right_height) / max(left_height, right_height)
        ramus_symmetric = height_diff_ratio <= 0.10
    else:
        ramus_symmetric = True
    
    # 下颌角对称性：暂时使用面积对称性近似
    left_area = _calculate_polygon_area(left_coords)
    right_area = _calculate_polygon_area(right_coords)
    
    if left_area == 0 and right_area == 0:
        gonial_symmetric = True
    elif max(left_area, right_area) > 0:
        area_diff_ratio = abs(left_area - right_area) / max(left_area, right_area)
        gonial_symmetric = area_diff_ratio <= 0.15
    else:
        gonial_symmetric = True
    
    # 生成 Detail
    details = []
    if not ramus_symmetric:
        details.append("下颌升支不对称")
    else:
        details.append("下颌升支对称")
    
    if not gonial_symmetric:
        details.append("下颌角不对称")
    else:
        details.append("下颌角对称")
    
    detail = "，".join(details)
    confidence = max(left_confidence, right_confidence)
    
    return {
        "RamusSymmetry": ramus_symmetric,
        "GonialAngleSymmetry": gonial_symmetric,
        "Detail": detail,
        "Confidence": round(float(confidence), 2),
    }


def _calculate_bounding_height(coordinates: List[List[float]]) -> float:
    """
    计算多边形的包围盒高度。
    
    Args:
        coordinates: [[x, y], ...] 多边形坐标点
    
    Returns:
        高度（像素）
    """
    if not coordinates or len(coordinates) < 2:
        return 0.0
    
    y_values = []
    for pt in coordinates:
        try:
            y_values.append(float(pt[1]))
        except (IndexError, TypeError, ValueError):
            continue
    
    if not y_values:
        return 0.0
    
    return max(y_values) - min(y_values)


# =============================================================================
# 5. 重算函数：上颌窦
# =============================================================================

def _recalculate_maxillary_sinus(
    maxillary_sinus_input: List[Dict[str, Any]],
    anatomy_masks: Dict[str, Dict[str, Any]],
    tooth_analysis: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    重算 MaxillarySinus。
    
    "因"：Inflammation, TypeClassification（透传）
    "果"：Pneumatization, RootEntryToothFDI, Detail（重算）
    
    Args:
        maxillary_sinus_input: 输入的 MaxillarySinus 列表
        anatomy_masks: 解析后的 AnatomyResults
        tooth_analysis: 牙齿分析列表
    
    Returns:
        重算后的 MaxillarySinus 列表
    """
    result = []
    
    # 构建牙齿 mask 索引
    tooth_masks = {}
    for tooth in tooth_analysis:
        fdi = tooth.get("FDI", "")
        seg_mask = tooth.get("SegmentationMask", {})
        coordinates = seg_mask.get("Coordinates", [])
        if fdi and coordinates:
            tooth_masks[fdi] = coordinates
    
    for item in maxillary_sinus_input:
        side = item.get("Side", "left")
        inflammation = item.get("Inflammation", False)
        type_classification = item.get("TypeClassification", 0)
        
        # 获取对应的上颌窦 mask
        sinus_label = f"sinus_{side}"
        sinus_coords = anatomy_masks.get(sinus_label, {}).get("coordinates", [])
        sinus_confidence = anatomy_masks.get(sinus_label, {}).get("confidence", 0.0)
        
        # 重算 Pneumatization（根据上颌窦与特定牙位的距离）
        # 左侧参考 26，右侧参考 16
        ref_tooth_fdi = "26" if side == "left" else "16"
        pneumatization = _calculate_pneumatization(
            sinus_coords=sinus_coords,
            ref_tooth_coords=tooth_masks.get(ref_tooth_fdi, []),
        )
        
        # 重算 RootEntryToothFDI（判断哪些牙根进入上颌窦）
        root_entry_teeth = _calculate_root_entry_teeth(
            sinus_coords=sinus_coords,
            tooth_masks=tooth_masks,
            side=side,
        )
        
        # 生成 Detail
        detail = _generate_sinus_detail(
            side=side,
            pneumatization=pneumatization,
            inflammation=inflammation,
            root_entry_teeth=root_entry_teeth,
        )
        
        result.append({
            "Side": side,
            "Pneumatization": pneumatization,
            "TypeClassification": type_classification,
            "Inflammation": inflammation,
            "RootEntryToothFDI": root_entry_teeth,
            "Detail": detail,
            "Confidence_Pneumatization": round(sinus_confidence, 2) if sinus_coords else 0.0,
            "Confidence_Inflammation": item.get("Confidence_Inflammation", 0.0),
        })
    
    return result


def _calculate_pneumatization(
    sinus_coords: List[List[float]],
    ref_tooth_coords: List[List[float]],
) -> int:
    """
    计算上颌窦气化程度。
    
    逻辑：根据上颌窦 mask 与参考牙位的距离/重叠程度判断。
    0=正常, 1=轻度气化, 2=过度气化
    
    Args:
        sinus_coords: 上颌窦 mask 坐标
        ref_tooth_coords: 参考牙位 mask 坐标（16/26）
    
    Returns:
        气化程度 (0/1/2)
    """
    if not sinus_coords or not ref_tooth_coords:
        return 0  # 无数据，默认正常
    
    # 计算上颌窦和牙齿的 bounding box
    sinus_bbox = _get_bounding_box(sinus_coords)
    tooth_bbox = _get_bounding_box(ref_tooth_coords)
    
    if not sinus_bbox or not tooth_bbox:
        return 0
    
    # 判断 Y 方向的距离/重叠
    # 如果上颌窦底部低于牙齿根尖，说明气化程度较高
    sinus_bottom = sinus_bbox[3]  # y_max
    tooth_top = tooth_bbox[1]  # y_min（根尖位置）
    
    # 计算重叠程度
    overlap = sinus_bottom - tooth_top
    tooth_height = tooth_bbox[3] - tooth_bbox[1]
    
    if tooth_height <= 0:
        return 0
    
    overlap_ratio = overlap / tooth_height
    
    if overlap_ratio >= 0.5:
        return 2  # 过度气化
    elif overlap_ratio >= 0.2:
        return 1  # 轻度气化
    else:
        return 0  # 正常


def _calculate_root_entry_teeth(
    sinus_coords: List[List[float]],
    tooth_masks: Dict[str, List[List[float]]],
    side: str,
) -> List[str]:
    """
    计算哪些牙根进入上颌窦。
    
    逻辑：检查上颌牙齿（第一、二象限）的 mask 与上颌窦 mask 是否有交集。
    
    Args:
        sinus_coords: 上颌窦 mask 坐标
        tooth_masks: 牙齿 mask 字典
        side: 上颌窦侧别 (left/right)
    
    Returns:
        进入上颌窦的牙齿 FDI 列表
    """
    if not sinus_coords:
        return []
    
    sinus_bbox = _get_bounding_box(sinus_coords)
    if not sinus_bbox:
        return []
    
    # 根据侧别确定相关象限
    # 左侧上颌窦：检查第二象限（21-28）
    # 右侧上颌窦：检查第一象限（11-18）
    if side == "left":
        relevant_fdis = [str(i) for i in range(21, 29)]
    else:
        relevant_fdis = [str(i) for i in range(11, 19)]
    
    root_entry_teeth = []
    
    for fdi in relevant_fdis:
        tooth_coords = tooth_masks.get(fdi, [])
        if not tooth_coords:
            continue
        
        tooth_bbox = _get_bounding_box(tooth_coords)
        if not tooth_bbox:
            continue
        
        # 检查 bounding box 是否有交集
        if _bbox_intersects(sinus_bbox, tooth_bbox):
            root_entry_teeth.append(fdi)
    
    return root_entry_teeth


def _get_bounding_box(coordinates: List[List[float]]) -> Optional[List[float]]:
    """
    获取多边形的包围盒。
    
    Args:
        coordinates: [[x, y], ...] 多边形坐标点
    
    Returns:
        [x_min, y_min, x_max, y_max] 或 None
    """
    if not coordinates or len(coordinates) < 2:
        return None
    
    x_values = []
    y_values = []
    
    for pt in coordinates:
        try:
            x_values.append(float(pt[0]))
            y_values.append(float(pt[1]))
        except (IndexError, TypeError, ValueError):
            continue
    
    if not x_values or not y_values:
        return None
    
    return [min(x_values), min(y_values), max(x_values), max(y_values)]


def _bbox_intersects(bbox1: List[float], bbox2: List[float]) -> bool:
    """
    检查两个 bounding box 是否有交集。
    
    Args:
        bbox1, bbox2: [x_min, y_min, x_max, y_max]
    
    Returns:
        是否有交集
    """
    return not (
        bbox1[2] < bbox2[0] or  # bbox1 在 bbox2 左边
        bbox1[0] > bbox2[2] or  # bbox1 在 bbox2 右边
        bbox1[3] < bbox2[1] or  # bbox1 在 bbox2 上边
        bbox1[1] > bbox2[3]     # bbox1 在 bbox2 下边
    )


def _generate_sinus_detail(
    side: str,
    pneumatization: int,
    inflammation: bool,
    root_entry_teeth: List[str],
) -> str:
    """
    生成上颌窦描述文本。
    """
    side_cn = "左" if side == "left" else "右"
    
    # 气化描述
    if pneumatization == 0:
        pneum_desc = f"{side_cn}上颌窦气化正常"
    elif pneumatization == 1:
        pneum_desc = f"{side_cn}上颌窦轻度气化"
    else:
        pneum_desc = f"{side_cn}上颌窦过度气化"
    
    parts = [pneum_desc]
    
    # 牙根进入描述
    if root_entry_teeth:
        teeth_str = "、".join(root_entry_teeth)
        parts.append(f"{teeth_str}牙位牙根进入上颌窦")
    
    # 炎症描述
    if inflammation:
        parts.append("建议耳鼻喉科会诊")
    
    return "，".join(parts) + "。"


# =============================================================================
# 6. 重算函数：缺牙推导
# =============================================================================

# 完整恒牙 FDI 编号（不含智齿，共28颗）
ALL_PERMANENT_TEETH = [
    "11", "12", "13", "14", "15", "16", "17",  # 第一象限
    "21", "22", "23", "24", "25", "26", "27",  # 第二象限
    "31", "32", "33", "34", "35", "36", "37",  # 第三象限
    "41", "42", "43", "44", "45", "46", "47",  # 第四象限
]


def _recalculate_missing_teeth(tooth_analysis: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    从检测到的牙齿列表反推缺失牙。
    
    Args:
        tooth_analysis: 检测到的牙齿列表
    
    Returns:
        缺失牙列表
    """
    # 提取检测到的 FDI
    detected_fdis: Set[str] = set()
    for tooth in tooth_analysis:
        fdi = tooth.get("FDI", "")
        if fdi:
            detected_fdis.add(fdi)
    
    # 计算缺失牙（不含智齿和乳牙）
    missing_teeth = []
    for fdi in ALL_PERMANENT_TEETH:
        if fdi not in detected_fdis:
            missing_teeth.append({
                "FDI": fdi,
                "Reason": "missing",
                "Detail": f"{fdi}牙位缺牙",
            })
    
    return missing_teeth


# =============================================================================
# 7. 重算函数：智齿摘要
# =============================================================================

def _recalculate_third_molar_summary(
    third_molar_summary_input: Dict[str, Dict[str, Any]],
    tooth_analysis: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    重算 ThirdMolarSummary。
    
    "因"：Impactions（透传）
    "果"：Level, Detail（重算）
    
    Level 定义：
        0 = 阻生（有 Impacted 属性）
        1 = 牙胚（检测到但标记为 tooth_germ）
        2 = 待萌出（检测到但标记为 to_be_erupted）
        4 = 未见智齿（未检测到）
    
    Args:
        third_molar_summary_input: 输入的 ThirdMolarSummary
        tooth_analysis: 牙齿分析列表
    
    Returns:
        重算后的 ThirdMolarSummary
    """
    # 构建检测到的智齿属性索引
    wisdom_tooth_info: Dict[str, Dict[str, Any]] = {}
    
    for tooth in tooth_analysis:
        fdi = tooth.get("FDI", "")
        if fdi not in WISDOM_TEETH_FDI:
            continue
        
        properties = tooth.get("Properties", [])
        confidence = tooth.get("Confidence", 0.0)
        
        # 提取属性值
        prop_values = set()
        for prop in properties:
            if isinstance(prop, dict):
                prop_values.add(prop.get("Value", "").lower())
            elif isinstance(prop, str):
                prop_values.add(prop.lower())
        
        wisdom_tooth_info[fdi] = {
            "properties": prop_values,
            "confidence": confidence,
        }
    
    # 生成结果
    result = {}
    
    for fdi in WISDOM_TEETH_FDI:
        input_entry = third_molar_summary_input.get(fdi, {})
        impactions = input_entry.get("Impactions")  # 透传
        
        if fdi in wisdom_tooth_info:
            # 检测到智齿
            info = wisdom_tooth_info[fdi]
            props = info["properties"]
            confidence = info["confidence"]
            
            # 判断 Level
            if "impacted" in props or impactions == "Impacted":
                level = 0
                detail = "阻生"
                impactions = "Impacted"
            elif "tooth_germ" in props:
                level = 1
                detail = "牙胚状态（未形成牙根）"
            elif "to_be_erupted" in props:
                level = 2
                detail = "待萌出（垂直生长，无阻碍）"
            else:
                # 其他情况：已萌出或正常
                level = 3
                detail = "已萌出"
            
            result[fdi] = {
                "Level": level,
                "Impactions": impactions,
                "Detail": detail,
                "Confidence": round(float(confidence), 2),
            }
        else:
            # 未检测到智齿
            result[fdi] = {
                "Level": 4,
                "Impactions": None,
                "Detail": "未见智齿",
                "Confidence": 0.0,
            }
    
    return result


# =============================================================================
# 8. 重算函数：种植体分析
# =============================================================================

def _recalculate_implant_analysis(implant_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    重算 ImplantAnalysis。
    
    "因"：Items[*].BBox, Confidence（透传）
    "果"：TotalCount, QuadrantCounts, Detail, Items[*].Quadrant（重算）
    
    Args:
        implant_items: 种植体检测项列表
    
    Returns:
        重算后的 ImplantAnalysis
    """
    # 统计象限
    quadrant_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    formatted_items = []
    
    for item in implant_items:
        bbox = item.get("BBox", [])
        confidence = item.get("Confidence", 0.0)
        item_id = item.get("ID", "implant")
        
        # 根据 bbox 中心点确定象限
        quadrant_id = _determine_quadrant_from_bbox(bbox)
        quadrant_name = QUADRANT_MAP.get(quadrant_id, "未知象限")
        
        if quadrant_id in quadrant_counts:
            quadrant_counts[quadrant_id] += 1
        
        formatted_items.append({
            "ID": item_id,
            "Quadrant": quadrant_name,
            "Confidence": round(float(confidence), 2),
            "BBox": bbox,
            "Detail": f"{quadrant_name}检测到种植体",
        })
    
    # 生成 Detail
    detail_parts = []
    for quad_id in [1, 2, 3, 4]:
        count = quadrant_counts[quad_id]
        if count > 0:
            quad_name = QUADRANT_MAP[quad_id]
            detail_parts.append(f"{quad_name}存在种植体，个数为{count}")
    
    detail = "；".join(detail_parts) if detail_parts else "未检测到种植体"
    
    return {
        "TotalCount": len(implant_items),
        "Items": formatted_items,
        "Detail": detail,
        "QuadrantCounts": {
            "Q1": quadrant_counts[1],
            "Q2": quadrant_counts[2],
            "Q3": quadrant_counts[3],
            "Q4": quadrant_counts[4],
        },
    }


def _determine_quadrant_from_bbox(bbox: List[float]) -> int:
    """
    根据 bbox 中心点确定象限。
    
    假设图像中心为原点：
        - 第一象限：右上（x > center, y < center）
        - 第二象限：左上（x < center, y < center）
        - 第三象限：左下（x < center, y > center）
        - 第四象限：右下（x > center, y > center）
    
    注意：全景片中通常使用相对坐标，这里简化处理。
    实际应该根据图像尺寸计算中心点。
    这里使用 x 坐标判断左右，假设图像宽度约 2000-3000 像素。
    
    Args:
        bbox: [x1, y1, x2, y2] 或 [x, y, w, h]
    
    Returns:
        象限 ID (1-4)
    """
    if not bbox or len(bbox) < 4:
        return 1  # 默认第一象限
    
    # 假设 bbox 格式为 [x1, y1, x2, y2]
    x_center = (bbox[0] + bbox[2]) / 2
    y_center = (bbox[1] + bbox[3]) / 2
    
    # 假设图像中心约为 (1000, 500)
    # 实际应该从 ImageSpacing 或图像元数据获取
    image_center_x = 1000.0
    image_center_y = 500.0
    
    # 确定象限
    if x_center >= image_center_x:
        # 右侧
        if y_center <= image_center_y:
            return 1  # 右上
        else:
            return 4  # 右下
    else:
        # 左侧
        if y_center <= image_center_y:
            return 2  # 左上
        else:
            return 3  # 左下


# =============================================================================
# 9. 重算函数：根尖密度影分析
# =============================================================================

def _recalculate_root_tip_density(density_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    重算 RootTipDensityAnalysis。
    
    "因"：Items[*]（透传 BBox, Confidence, ID）
    "果"：TotalCount, QuadrantCounts, Detail, Items[*].Quadrant（重算）
    
    Args:
        density_items: 密度影检测项列表
    
    Returns:
        重算后的 RootTipDensityAnalysis
    """
    # 统计象限
    quadrant_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    formatted_items = []
    
    for item in density_items:
        bbox = item.get("BBox", [])
        confidence = item.get("Confidence", 0.0)
        item_id = item.get("ID", "density")
        
        # 获取原始 Quadrant（可能是数字或字符串）
        original_quadrant = item.get("Quadrant")
        
        # 根据 bbox 重新确定象限
        quadrant_id = _determine_quadrant_from_bbox(bbox)
        quadrant_name = QUADRANT_MAP.get(quadrant_id, "未知象限")
        
        if quadrant_id in quadrant_counts:
            quadrant_counts[quadrant_id] += 1
        
        # 根据 ID 确定密度类型描述
        if "low" in str(item_id).lower():
            density_type = "低密度影"
        elif "high" in str(item_id).lower():
            density_type = "高密度影"
        else:
            density_type = "密度影"
        
        formatted_items.append({
            "ID": item_id,
            "Quadrant": quadrant_id,  # 保持原格式为数字
            "Confidence": round(float(confidence), 2),
            "BBox": bbox,
            "Detail": f"{quadrant_name}检测到{density_type}",
        })
    
    # 生成 Detail
    detail_parts = []
    for quad_id in [1, 2, 3, 4]:
        count = quadrant_counts[quad_id]
        if count > 0:
            quad_name = QUADRANT_MAP[quad_id]
            detail_parts.append(f"{quad_name}检测到根尖密度影，个数为{count}")
    
    detail = "；".join(detail_parts) if detail_parts else "未检测到根尖密度影"
    
    return {
        "TotalCount": len(density_items),
        "Items": formatted_items,
        "Detail": detail,
        "QuadrantCounts": {
            "Q1": quadrant_counts[1],
            "Q2": quadrant_counts[2],
            "Q3": quadrant_counts[3],
            "Q4": quadrant_counts[4],
        },
    }

