# -*- coding: utf-8 -*-
"""
全景片报告生成工具 (Assembler) - v2.0
严格对齐 example_pano_result.json 规范
"""

import logging
import datetime
import numpy as np
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# =============================================================================
# 0. 常量与映射
# =============================================================================

MORPHOLOGY_MAP = {
    0: {"detail": "髁突形态正常", "label": "正常"},
    1: {"detail": "髁突形态吸收", "label": "吸收"},
    2: {"detail": "髁突形态疑似异常", "label": "疑似"},
}

# 象限数字到中文映射
QUADRANT_MAP = {
    1: "第一象限",
    2: "第二象限",
    3: "第三象限",
    4: "第四象限",
}

# 智齿 FDI 编号
WISDOM_TEETH_FDI = ["18", "28", "38", "48"]

# 乳牙 FDI 编号范围 (51-85)
DECIDUOUS_TEETH_FDI = [
    "51", "52", "53", "54", "55",  # 上颌右侧乳牙
    "61", "62", "63", "64", "65",  # 上颌左侧乳牙
    "71", "72", "73", "74", "75",  # 下颌左侧乳牙
    "81", "82", "83", "84", "85"   # 下颌右侧乳牙
]

# 属性到中文描述映射（用于 ToothAnalysis.Properties 格式化）
ATTRIBUTE_DESCRIPTION_MAP = {
    "area": "病灶区域",
    "carious_lesion": "龋坏",
    "curved_short_root": "牙根形态弯曲短小",
    "embedded_tooth": "埋伏牙",
    "erupted": "已萌出",
    "impacted": "阻生",
    "implant": "种植体病灶",
    "not_visible": "不可见",
    "periodontal": "牙周病灶",
    "rct_treated": "根管治疗",
    "residual_crown": "残冠",
    "residual_root": "残根",
    "restored_tooth": "修复牙",
    "retained_primary_tooth": "滞留乳牙",
    "root_absorption": "牙根吸收",
    "to_be_erupted": "待萌出",
    "tooth_germ": "牙胚",
    "wisdom_tooth_impaction": "智齿阻生",
}


# =============================================================================
# 1. 核心对外接口
# =============================================================================

def generate_standard_output(
        metadata: Dict[str, Any],
        inference_results: Dict[str, Any],
        pixel_spacing: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    主组装函数：接收所有模块结果，生成最终 JSON

    Args:
        metadata: 元数据 (ImageName, DiagnosisID, AnalysisTime)
        inference_results: 各模块推理结果
            - condyle_seg: 髁突分割结果
            - condyle_det: 髁突检测结果
            - mandible: 下颌骨分割结果
            - implant: 种植体检测结果
            - teeth: 牙齿分割结果
            - teeth_attribute1牙齿属性检测结果1
 teeth_attribute1_results (fallback print) = {'attributes_detected': [{'attribute': 'restored_tooth', 'bbox': [644.75732421875, 325.9394226074219, 782.6345825195312, 594.7744750976562], 'area_pixels': 37066, 'relative_area': 0.012177010998129845}, {'attribute': 'restored_tooth', 'bbox': [1657.54931640625, 537.9069213867188, 1864.6363525390625, 724.3341674804688], 'area_pixels': 38606, 'relative_area': 0.012683072127401829}, {'attribute': 'restored_tooth', 'bbox': [528.81201171875, 332.9461364746094, 645.06640625, 574.357666015625], 'area_pixels': 28065, 'relative_area': 0.009219971485435963}, {'attribute': 'restored_tooth', 'bbox': [1129.281494140625, 359.2254638671875, 1213.2252197265625, 626.2619018554688], 'area_pixels': 22416, 'relative_area': 0.0073641217313706875}, {'attribute': 'restored_tooth', 'bbox': [1681.9967041015625, 289.2119140625, 1780.6429443359375, 534.9676513671875], 'area_pixels': 24242, 'relative_area': 0.007964277639985085}, {'attribute': 'restored_tooth', 'bbox': [1431.4906005859375, 305.547119140625, 1516.9332275390625, 593.5940551757812], 'area_pixels': 24611, 'relative_area': 0.008085372857749462}, {'attribute': 'restored_tooth', 'bbox': [1217.554443359375, 359.1302185058594, 1303.4571533203125, 625.7640380859375], 'area_pixels': 22904, 'relative_area': 0.007524615619331598}, {'attribute': 'restored_tooth', 'bbox': [868.539306640625, 603.3043823242188, 989.8744506835938, 873.3271484375], 'area_pixels': 32763, 'relative_area': 0.01076339278370142}, {'attribute': 'restored_tooth', 'bbox': [1509.1873779296875, 303.8427734375, 1580.267333984375, 579.864990234375], 'area_pixels': 19619, 'relative_area': 0.006445452105253935}, {'attribute': 'restored_tooth', 'bbox': [1573.0150146484375, 297.5483093261719, 1690.6900634765625, 577.6265258789062], 'area_pixels': 32958, 'relative_area': 0.010827443562448025}, {'attribute': 'restored_tooth', 'bbox': [1473.1741943359375, 636.4564819335938, 1552.853759765625, 877.3297729492188], 'area_pixels': 19192, 'relative_area': 0.006305184680968523}, {'attribute': 'restored_tooth', 'bbox': [1342.8511962890625, 673.2179565429688, 1403.2705078125, 891.103515625], 'area_pixels': 13164, 'relative_area': 0.004324803594499826}, {'attribute': 'restored_tooth', 'bbox': [960.703369140625, 618.9495849609375, 1073.1361083984375, 874.2969970703125], 'area_pixels': 28709, 'relative_area': 0.009431622922420502}], 'attribute_counts': {'restored_tooth': 13}, 'summary': '检测到 13 个牙齿属性实例，涉及 1 种类 型。 最常见: restored_tooth (13)', 'total_attributes': 13, 'boxes': [[644.75732421875, 325.9394226074219, 782.6345825195312, 594.7744750976562], [1657.54931640625, 537.9069213867188, 1864.6363525390625, 724.3341674804688], [528.81201171875, 332.9461364746094, 645.06640625, 574.357666015625], [1129.281494140625, 359.2254638671875, 1213.2252197265625, 626.2619018554688], [1681.9967041015625, 289.2119140625, 1780.6429443359375, 534.9676513671875], [1431.4906005859375, 305.547119140625, 1516.9332275390625, 593.5940551757812], [1217.554443359375, 359.1302185058594, 1303.4571533203125, 625.7640380859375], [868.539306640625, 603.3043823242188, 989.8744506835938, 873.3271484375], [1509.1873779296875, 303.8427734375, 1580.267333984375, 579.864990234375], [1573.0150146484375, 297.5483093261719, 1690.6900634765625, 577.6265258789062], [1473.1741943359375, 636.4564819335938, 1552.853759765625, 877.3297729492188], [1342.8511962890625, 673.2179565429688, 1403.2705078125, 891.103515625], [960.703369140625, 618.9495849609375, 1073.1361083984375, 874.2969970703125]], 'raw_boxes': array([[ 644.7573 ,  325.93942,  782.6346 ,  594.7745 ],

            - teeth_attribute2牙齿属性检测结果2
            - curved_short_root牙根形态弯曲短小检测
            - erupted_wisdomteeth智齿阻生检测
            - sinus: 上颌窦分析结果

    Returns:
        dict: 完整的全景片分析报告
    """
    # 提取各模块数据
    condyle_seg = inference_results.get("condyle_seg", {})
    condyle_det = inference_results.get("condyle_det", {})
    mandible_res = inference_results.get("mandible", {})
    implant_res = inference_results.get("implant", {})
    teeth_res = inference_results.get("teeth", {})
    sinus_res = inference_results.get("sinus", {})
    # 新增：提取单独的牙齿属性模块结果
    teeth_attribute1_res = inference_results.get("teeth_attribute1", {})
    teeth_attribute2_res = inference_results.get("teeth_attribute2", {})
    curved_short_root_res = inference_results.get("curved_short_root", {})
    erupted_wisdomteeth_res = inference_results.get("erupted_wisdomteeth", {})
    rootTipDensity_res = inference_results.get("rootTipDensity", {})

    # 1. 初始化基础骨架（严格按照 example_pano_result.json 顺序）
    # 处理 ImageSpacing（像素间距/比例尺）
    # API 层（server/api.py）是唯一的默认值来源，此处不再设置默认值
    if not pixel_spacing or not pixel_spacing.get("scale_x"):
        # 如果走到这里，说明调用方存在 bug（API 层应该保证有值）
        raise ValueError(
            "[PixelSpacing] pixel_spacing is required but not provided. "
            "This is likely a bug in the calling code. "
            "API layer (server/api.py) should guarantee pixel_spacing is always set."
        )
    
    spacing_x = pixel_spacing["scale_x"]
    spacing_y = pixel_spacing.get("scale_y", spacing_x)
    spacing_source = pixel_spacing.get("source", "unknown")
    logger.info(f"[PixelSpacing] Using value from {spacing_source}: X={spacing_x:.4f}, Y={spacing_y:.4f} mm/pixel")
    
    report = {
        "Metadata": _format_metadata(metadata),
        "ImageSpacing": {  # 图像像素间距信息 - 用于空间测量计算
            "X": spacing_x,
            "Y": spacing_y,
            "Unit": "mm/pixel"
        },
        "AnatomyResults": [],  # 将从 condyle_seg 填充
        "JointAndMandible": _get_joint_mandible_default(),
        "MaxillarySinus": _get_maxillary_sinus_mock(),  # 真实数据：从 sinus 模块填充（如果有）
        "PeriodontalCondition": _get_periodontal_mock(),  # Mock: 无模型
        "MissingTeeth": [],  # 真实数据：从 teeth 模块填充
        "ThirdMolarSummary": {},  # 真实数据：从 teeth 模块填充
        "ImplantAnalysis": _get_implant_default(),  # 真实数据：从 implant 模块填充
        "RootTipDensityAnalysis": _get_root_tip_density_default(),  # 真实数据：从 rootTipDensity 模块填充
        "ToothAnalysis": []  # 部分真实：从 teeth 模块填充（但 Properties 为 mock）
    }

    # 2. 组装 AnatomyResults (髁突和下颌分支分割掩码) - 真实数据
    anatomy_results_list = []

    # 2.1 添加髁突分割结果
    logger.info(f"[generate_standard_output] condyle_seg exists: {bool(condyle_seg)}")
    if condyle_seg:
        logger.info(f"[generate_standard_output] Calling format_anatomy_results for condyle...")
        condyle_anatomy_data = format_anatomy_results(condyle_seg)
        logger.info(f"[generate_standard_output] Condyle AnatomyResults count: {len(condyle_anatomy_data)}")
        anatomy_results_list.extend(condyle_anatomy_data)

    # 2.2 添加下颌分支分割结果
    logger.info(f"[generate_standard_output] mandible_res exists: {bool(mandible_res)}")
    if mandible_res:
        logger.info(f"[generate_standard_output] Calling format_mandible_anatomy_results...")
        mandible_anatomy_data = format_mandible_anatomy_results(mandible_res)
        logger.info(f"[generate_standard_output] Mandible AnatomyResults count: {len(mandible_anatomy_data)}")
        anatomy_results_list.extend(mandible_anatomy_data)

    report["AnatomyResults"] = anatomy_results_list

    # 3. 组装髁突部分 (CondyleAssessment) - 真实数据

    if condyle_seg or condyle_det:
        condyle_data = format_joint_report(condyle_seg, condyle_det)
        report["JointAndMandible"]["CondyleAssessment"] = condyle_data["CondyleAssessment"]

    # 4. 组装下颌骨部分 (Mandible) - 真实数据
    if mandible_res and "analysis" in mandible_res:
        mandible_data = format_mandible_report(mandible_res["analysis"])

        # 合并下颌骨数据
        existing_detail = report["JointAndMandible"].get("Detail", "")
        new_detail = mandible_data.get("Detail", "")

        report["JointAndMandible"]["RamusSymmetry"] = mandible_data["RamusSymmetry"]
        report["JointAndMandible"]["GonialAngleSymmetry"] = mandible_data["GonialAngleSymmetry"]
        report["JointAndMandible"]["Confidence"] = mandible_data["Confidence"]

        # 拼接 Detail
        if existing_detail and new_detail:
            report["JointAndMandible"]["Detail"] = f"{existing_detail}；{new_detail}"
        elif new_detail:
            report["JointAndMandible"]["Detail"] = new_detail

    # 5. 组装种植体分析 (ImplantAnalysis) - 真实数据
    if implant_res:
        implant_data = format_implant_report(implant_res)
        report["ImplantAnalysis"] = implant_data

    # 6. 组装牙齿分割结果 (MissingTeeth, ThirdMolarSummary, ToothAnalysis) - 真实数据
    if teeth_res:
        # 传递单独的牙齿属性模块结果到 format_teeth_report（内部进行IoU匹配整合）
        teeth_data = format_teeth_report(
            teeth_res,
            teeth_attribute1_res,
            teeth_attribute2_res,
            curved_short_root_res,
            erupted_wisdomteeth_res
        )
        report["MissingTeeth"] = teeth_data["MissingTeeth"]
        report["ThirdMolarSummary"] = teeth_data["ThirdMolarSummary"]
        report["ToothAnalysis"] = teeth_data["ToothAnalysis"]

    # 7. 组装上颌窦分析 (MaxillarySinus) - 真实数据
    if sinus_res:
        sinus_data = format_sinus_report(sinus_res)
        report["MaxillarySinus"] = sinus_data["MaxillarySinus"]

        # 可选：将上颌窦 mask 添加到 AnatomyResults（如果有 mask 信息）
        if "masks_info" in sinus_res and sinus_res["masks_info"]:
            sinus_anatomy_data = format_sinus_anatomy_results(sinus_res)
            if sinus_anatomy_data:
                report["AnatomyResults"].extend(sinus_anatomy_data)
                logger.info(f"[generate_standard_output] Added {len(sinus_anatomy_data)} sinus AnatomyResults")

    # 8. 组装根尖低密度影分析 (RootTipDensityAnalysis) - 真实数据
    if rootTipDensity_res:
        rootTipDensity_data = format_root_tip_density_report(rootTipDensity_res)
        report["RootTipDensityAnalysis"] = rootTipDensity_data

    return report


# =============================================================================
# 2. 格式化函数 (真实数据处理)
# =============================================================================

def format_anatomy_results(condyle_seg: dict) -> List[dict]:
    """
    格式化 AnatomyResults（解剖结构分割掩码）- 髁突部分

    Args:
        condyle_seg: 髁突分割结果 {raw_features: {left: {...}, right: {...}}, ...}

    Returns:
        list: AnatomyResults 列表
    """
    anatomy_results = []

    # 调试日志
    logger.info(f"[format_anatomy_results] condyle_seg keys: {list(condyle_seg.keys()) if condyle_seg else 'EMPTY'}")

    seg_features = condyle_seg.get("raw_features", {})
    logger.info(f"[format_anatomy_results] seg_features keys: {list(seg_features.keys()) if seg_features else 'EMPTY'}")

    seg_left = seg_features.get("left", {})
    seg_right = seg_features.get("right", {})

    logger.info(f"[format_anatomy_results] seg_left exists: {seg_left.get('exists', False)}, keys: {list(seg_left.keys())}")
    logger.info(f"[format_anatomy_results] seg_right exists: {seg_right.get('exists', False)}, keys: {list(seg_right.keys())}")

    # 左侧髁突
    if seg_left.get("exists", False):
        left_mask = seg_left.get("mask", None)
        left_contour = seg_left.get("contour", [])
        left_contour = seg_left.get("contour", [])
        # 跳过 RLE 生成，避免数据过大导致 Redis Protocol Error
        
        anatomy_results.append({
            "Label": "condyle_left",
            "Confidence": round(seg_left.get("confidence", 0.0), 2),
            "SegmentationMask": {
                "Type": "Polygon",
                "Coordinates": left_contour if left_contour else [],
                "SerializedMask": ""
            }
        })

    # 右侧髁突
    if seg_right.get("exists", False):
        right_contour = seg_right.get("contour", [])
        # 跳过 RLE 生成，避免数据过大导致 Redis Protocol Error
        
        anatomy_results.append({
            "Label": "condyle_right",
            "Confidence": round(seg_right.get("confidence", 0.0), 2),
            "SegmentationMask": {
                "Type": "Polygon",
                "Coordinates": right_contour if right_contour else [],
                "SerializedMask": ""
            }
        })

    return anatomy_results


def format_mandible_anatomy_results(mandible_seg: dict) -> List[dict]:
    """
    格式化 AnatomyResults（解剖结构分割掩码）- 下颌分支部分

    Args:
        mandible_seg: 下颌骨分割结果 {raw_features: {left: {...}, right: {...}}, ...}

    Returns:
        list: AnatomyResults 列表，包含 mandible_left 和 mandible_right
    """
    anatomy_results = []

    # 调试日志
    logger.info(f"[format_mandible_anatomy_results] mandible_seg keys: {list(mandible_seg.keys()) if mandible_seg else 'EMPTY'}")

    seg_features = mandible_seg.get("raw_features", {})
    logger.info(f"[format_mandible_anatomy_results] seg_features keys: {list(seg_features.keys()) if seg_features else 'EMPTY'}")

    seg_left = seg_features.get("left", {})
    seg_right = seg_features.get("right", {})

    logger.info(f"[format_mandible_anatomy_results] seg_left exists: {seg_left.get('exists', False)}, keys: {list(seg_left.keys())}")
    logger.info(f"[format_mandible_anatomy_results] seg_right exists: {seg_right.get('exists', False)}, keys: {list(seg_right.keys())}")

    # 左侧下颌分支
    if seg_left.get("exists", False):
        left_contour = seg_left.get("contour", [])
        # 跳过 RLE 生成，避免数据过大导致 Redis Protocol Error
        
        anatomy_results.append({
            "Label": "mandible_left",
            "Confidence": round(seg_left.get("confidence", 0.0), 2),
            "SegmentationMask": {
                "Type": "Polygon",
                "Coordinates": left_contour if left_contour else [],
                "SerializedMask": ""
            }
        })

    # 右侧下颌分支
    if seg_right.get("exists", False):
        right_contour = seg_right.get("contour", [])
        # 跳过 RLE 生成，避免数据过大导致 Redis Protocol Error
        
        anatomy_results.append({
            "Label": "mandible_right",
            "Confidence": round(seg_right.get("confidence", 0.0), 2),
            "SegmentationMask": {
                "Type": "Polygon",
                "Coordinates": right_contour if right_contour else [],
                "SerializedMask": ""
            }
        })

    return anatomy_results


def format_joint_report(condyle_seg: dict, condyle_det: dict) -> dict:
    """
    格式化髁突(Condyle)部分 - 真实数据

    Args:
        condyle_seg: 髁突分割结果 {raw_features: {left: {...}, right: {...}}, analysis: {...}}
        condyle_det: 髁突检测结果 {left: {class_id, confidence, bbox}, right: {...}}

    Returns:
        dict: 包含 CondyleAssessment 的字典
    """
    # 获取检测结果中的形态学分类 (class_id: 0=正常, 1=吸收, 2=疑似)
    det_left = condyle_det.get("left", {})
    det_right = condyle_det.get("right", {})

    left_morphology = det_left.get("class_id", 0)
    right_morphology = det_right.get("class_id", 0)
    left_conf_det = det_left.get("confidence", 0.0)
    right_conf_det = det_right.get("confidence", 0.0)

    # 获取分割结果中的置信度和存在性
    seg_features = condyle_seg.get("raw_features", {})
    seg_left = seg_features.get("left", {})
    seg_right = seg_features.get("right", {})

    left_exists = seg_left.get("exists", False)
    right_exists = seg_right.get("exists", False)
    left_conf_seg = seg_left.get("confidence", 0.0)
    right_conf_seg = seg_right.get("confidence", 0.0)

    # 综合置信度
    if left_exists and left_conf_seg > 0:
        left_confidence = (left_conf_det + left_conf_seg) / 2
    else:
        left_confidence = left_conf_det

    if right_exists and right_conf_seg > 0:
        right_confidence = (right_conf_det + right_conf_seg) / 2
    else:
        right_confidence = right_conf_det

    # 生成详细描述
    left_detail = MORPHOLOGY_MAP.get(left_morphology, MORPHOLOGY_MAP[0])["detail"]
    right_detail = MORPHOLOGY_MAP.get(right_morphology, MORPHOLOGY_MAP[0])["detail"]

    # 判断对称性
    seg_analysis = condyle_seg.get("analysis", {})
    is_symmetric = seg_analysis.get("is_symmetric", True)

    # 判断整体对称性 (0=对称, 1=左侧大, 2=右侧大)
    overall_symmetry = 0
    if not is_symmetric:
        metrics = seg_analysis.get("metrics", {})
        left_area = metrics.get("left_area", 0)
        right_area = metrics.get("right_area", 0)
        if left_area > right_area:
            overall_symmetry = 1  # 左侧大
        elif right_area > left_area:
            overall_symmetry = 2  # 右侧大

    # 构建 CondyleAssessment
    condyle_assessment = {
        "condyle_Left": {
            "Morphology": left_morphology,
            "Detail": left_detail,
            "Confidence": float(round(left_confidence, 2))
        },
        "condyle_Right": {
            "Morphology": right_morphology,
            "Detail": right_detail,
            "Confidence": float(round(right_confidence, 2))
        },
        "OverallSymmetry": overall_symmetry,
        "Confidence_Overall": float(round(max(left_confidence, right_confidence), 2))
    }

    return {"CondyleAssessment": condyle_assessment}


def format_mandible_report(analysis_result: dict) -> dict:
    """
    格式化下颌骨(Mandible)部分 - 真实数据
    """
    confidence = float(analysis_result.get("Confidence", 0.0))

    return {
        "RamusSymmetry": bool(analysis_result.get("RamusSymmetry", False)),
        "GonialAngleSymmetry": bool(analysis_result.get("GonialAngleSymmetry", False)),
        "Detail": str(analysis_result.get("Detail", "未检测到下颌骨结构")),
        "Confidence": float(round(confidence, 2))
    }


def format_implant_report(implant_results: dict) -> dict:
    """
    格式化种植体(Implant)部分 - 真实数据

    Args:
        implant_results: {
            'implant_boxes': [{'box': [...], 'confidence': 0.95, 'quadrant': 1}, ...],
            'quadrant_counts': {1: 2, 2: 0, 3: 1, 4: 0}
        }

    Returns:
        dict: 符合 ImplantAnalysis 格式的字典
    """
    implant_boxes = implant_results.get("implant_boxes", [])
    quadrant_counts = implant_results.get("quadrant_counts", {1: 0, 2: 0, 3: 0, 4: 0})

    # 计算总数
    total_count = len(implant_boxes)

    # 格式化 Items
    items = []
    for idx, det in enumerate(implant_boxes):
        quadrant_id = det.get("quadrant", 0)
        quadrant_name = QUADRANT_MAP.get(quadrant_id, "未知象限")

        items.append({
            "ID": "implant",
            "Quadrant": quadrant_name,
            "Confidence": round(det.get("confidence", 0.0), 2),
            "BBox": det.get("box", []),
            "Detail": f"{quadrant_name}检测到种植体"
        })

    # 生成 Detail 文本
    detail_parts = []
    for quad_id in [1, 2, 3, 4]:
        count = quadrant_counts.get(quad_id, 0)
        if count > 0:
            quad_name = QUADRANT_MAP[quad_id]
            detail_parts.append(f"{quad_name}存在种植体，个数为{count}")

    detail = "；".join(detail_parts) if detail_parts else "未检测到种植体"

    # 格式化 QuadrantCounts
    quadrant_counts_formatted = {
        "Q1": quadrant_counts.get(1, 0),
        "Q2": quadrant_counts.get(2, 0),
        "Q3": quadrant_counts.get(3, 0),
        "Q4": quadrant_counts.get(4, 0),
    }

    return {
        "TotalCount": total_count,
        "Items": items,
        "Detail": detail,
        "QuadrantCounts": quadrant_counts_formatted
    }


def _bbox_iou_xyxy(box1, box2) -> float:
    """
    计算两个 bbox（xyxy 格式）的 IoU

    Args:
        box1, box2: [x1, y1, x2, y2]

    Returns:
        float: IoU 值 (0 ~ 1)
    """
    x1, y1, x2, y2 = box1
    x1g, y1g, x2g, y2g = box2

    # 交集
    inter_x1 = max(x1, x1g)
    inter_y1 = max(y1, y1g)
    inter_x2 = min(x2, x2g)
    inter_y2 = min(y2, y2g)

    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    # 各自面积
    area1 = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area2 = max(0.0, x2g - x1g) * max(0.0, y2g - y1g)

    if area1 <= 0 or area2 <= 0:
        return 0.0

    union = area1 + area2 - inter_area
    if union <= 0:
        return 0.0

    return inter_area / union

def format_teeth_report(
    teeth_results: dict,
    *args,
    **kwargs,
) -> dict:
    """
    格式化牙齿(Teeth)部分 - 真实数据 + 属性集成

    Args:
        teeth_results: {
            'report': str,
            'missing_teeth': [...],
            'wisdom_teeth': [...],
            'deciduous_teeth': [...],
            'detected_teeth': [{'fdi': str, 'class_name': str, 'mask_index': int, 'bbox': [x1,y1,x2,y2]}, ...],
            'raw_masks': np.ndarray,  # [N, H, W] (已经是原始图像尺寸)
            'segments': np.ndarray,  # [N, num_points, 2] 多边形坐标（原始图像坐标）
            'original_shape': tuple  # (H, W)
        }
        teeth_attribute1_res: 牙齿属性检测结果1 {'instances': [{'label': str, 'bbox': [x1,y1,x2,y2], 'score': float}, ...]}
        teeth_attribute2_res: 牙齿属性检测结果2 {'instances': [{'label': str, 'bbox': [x1,y1,x2,y2], 'score': float}, ...]}
        curved_short_root_res: 牙根形态弯曲短小检测 {'instances': [{'label': str, 'bbox': [x1,y1,x2,y2], 'score': float}, ...]}
        erupted_wisdomteeth_res: 智齿阻生检测 {'instances': [{'label': str, 'bbox': [x1,y1,x2,y2], 'score': float}, ...]}

    Returns:
        dict: 包含 MissingTeeth, ThirdMolarSummary, ToothAnalysis（Properties集成属性）
    """
    # Pipeline 已经完成牙位-属性绑定和缺失牙 / 智齿分析，这里只做格式转换
    missing_teeth_struct = teeth_results.get("MissingTeeth")
    third_molar_summary_struct = teeth_results.get("ThirdMolarSummary")
    tooth_attributes_map = teeth_results.get("ToothAttributes", {})

    # 兼容早期版本：若未提供结构化结果，则退回旧的文案解析逻辑
    missing_teeth_raw = teeth_results.get("missing_teeth", [])
    detected_teeth_list = teeth_results.get("detected_teeth", [])
    raw_masks = teeth_results.get("raw_masks", None)
    segments = teeth_results.get("segments", None)  # 直接从YOLO获取的多边形坐标
    original_shape = teeth_results.get("original_shape", None)

    # 1. MissingTeeth
    if missing_teeth_struct is not None:
        missing_teeth = missing_teeth_struct
    else:
        missing_teeth = []
        for item in missing_teeth_raw:
            fdi = _extract_fdi_from_text(item)
            if fdi:
                missing_teeth.append({
                    "FDI": fdi,
                    "Reason": "missing",
                    "Detail": item
                })

    # 2. ThirdMolarSummary
    if third_molar_summary_struct is not None:
        third_molar_summary = third_molar_summary_struct
    else:
        third_molar_summary = {}
        detected_wisdom_fdi = set()
        for tooth_info in detected_teeth_list:
            fdi = tooth_info.get("fdi", "")
            if fdi in WISDOM_TEETH_FDI:
                detected_wisdom_fdi.add(fdi)

        for fdi in WISDOM_TEETH_FDI:
            if fdi in detected_wisdom_fdi:
                third_molar_summary[fdi] = {
                    "Level": 1,
                    "Impactions": "Impacted",
                    "Detail": "阻生",
                    "Confidence": 0.85
                }
            else:
                third_molar_summary[fdi] = {
                    "Level": 4,
                    "Impactions": None,
                    "Detail": "未见智齿",
                    "Confidence": 0.0
                }

    # 3. 格式化 ToothAnalysis（所有检测到的牙齿）
    tooth_analysis = []

    # 遍历所有检测到的牙齿
    for tooth_info in detected_teeth_list:
        fdi = tooth_info.get("fdi", "")
        mask_index = tooth_info.get("mask_index", -1)

        if not fdi:
            logger.warning(f"[format_teeth_report] 牙齿信息缺少FDI，跳过: {tooth_info}")
            continue

        # 构建属性列表：优先使用 Pipeline 已经绑定好的属性
        # 将属性名称转换为符合规范的对象格式: {"Value": str, "Description": str, "Confidence": float}
        raw_properties = tooth_attributes_map.get(fdi, [])
        properties = []
        for attr_name in raw_properties:
            # 如果已经是字典格式，直接使用
            if isinstance(attr_name, dict):
                properties.append(attr_name)
            else:
                # 转换字符串为标准格式
                description = ATTRIBUTE_DESCRIPTION_MAP.get(attr_name, attr_name)
                properties.append({
                    "Value": attr_name,
                    "Description": description,
                    "Confidence": 0.85  # 默认置信度，后续可从模型输出获取
                })

        # 提取轮廓坐标：使用YOLO直接输出的segments（格式: [N, num_points, 2]）
        # 目标格式: [[x, y], [x, y], ...] 符合前端期望和规范
        coordinates = []
        serialized_mask = ""

        # 使用segments（直接从YOLO输出获取，已经是原始图像坐标）
        # segments可能是numpy数组 [N, num_points, 2] 或列表 [[poly1], [poly2], ...]
        if segments is not None and mask_index >= 0 and mask_index < len(segments):
            segment_coords = segments[mask_index]  # 可能是 [num_points, 2] 数组或列表

            if segment_coords is not None and len(segment_coords) > 0:
                # 转换为列表格式: [[x, y], [x, y], ...]
                if isinstance(segment_coords, np.ndarray):
                    coordinates = segment_coords.tolist()
                else:
                    coordinates = segment_coords

                # 确保格式正确：每个元素是 [x, y]
                if coordinates and len(coordinates) > 0:
                    # 验证第一个点的格式
                    if not isinstance(coordinates[0], (list, tuple)):
                        logger.error(f"Tooth {fdi}: Invalid segments format, expected [[x,y],...], got {type(coordinates[0])}")
                        coordinates = []
                    else:
                        # 确保所有点都是 [x, y] 格式（浮点数）
                        coordinates = [[float(pt[0]), float(pt[1])] for pt in coordinates if len(pt) >= 2]
                
                # 跳过 RLE 编码生成 - RLE 数据太大会导致 Redis Protocol Error
                # Coordinates 已经足够用于前端可视化
                # 如果需要 RLE，可以在客户端单独请求或从 Coordinates 重建
                serialized_mask = ""
        
        # 如果segments不可用，从mask提取轮廓（这是正确的做法）
        if not coordinates and raw_masks is not None and mask_index >= 0 and mask_index < len(raw_masks):
            coordinates, serialized_mask = _extract_mask_contour_fallback(
                raw_masks[mask_index],
                original_shape
            )
        elif not coordinates:
            logger.warning(f"[format_teeth_report] 牙齿 {fdi}: 无法提取坐标 - segments不可用且raw_masks也不可用或mask_index无效")

        # 最终验证
        if not coordinates:
            logger.error(f"[format_teeth_report] 牙齿 {fdi}: 未能提取坐标，SegmentationMask.Coordinates 将为空")
        else:
            logger.debug(f"[format_teeth_report] 牙齿 {fdi}: 提取 {len(coordinates)} 个坐标点")

        # 构建 ToothAnalysis 项
        tooth_analysis.append({
            "FDI": fdi,
            "Confidence": 0.85,  # Mock: 需要从模型输出获取实际置信度
            "SegmentationMask": {
                "Type": "Polygon",
                "Coordinates": coordinates,
                "SerializedMask": serialized_mask
            },
            "Properties": properties  # 集成IoU匹配的病理属性
        })

    return {
        "MissingTeeth": missing_teeth,
        "ThirdMolarSummary": third_molar_summary,
        "ToothAnalysis": tooth_analysis
    }

def format_sinus_report(sinus_results: dict) -> dict:
    """
    格式化上颌窦(MaxillarySinus)部分 - 真实数据

    Args:
        sinus_results: {
            'MaxillarySinus': [
                {
                    "Side": "left",
                    "Pneumatization": 0,
                    "TypeClassification": 0,
                    "Inflammation": False,
                    "RootEntryToothFDI": [],
                    "Detail": "左上颌窦气化良好。",
                    "Confidence_Pneumatization": 0.99,
                    "Confidence_Inflammation": 0.85
                },
                ...
            ],
            'masks_info': [...]  # 可选
        }

    Returns:
        dict: 包含 MaxillarySinus 的字典
    """
    maxillary_sinus_list = sinus_results.get("MaxillarySinus", [])

    # 如果没有数据，返回空列表
    if not maxillary_sinus_list:
        logger.warning("[format_sinus_report] No MaxillarySinus data found")
        return {"MaxillarySinus": []}

    # 验证并格式化每个结果
    formatted_list = []
    for item in maxillary_sinus_list:
        formatted_item = {
            "Side": item.get("Side", "left"),
            "Pneumatization": int(item.get("Pneumatization", 0)),
            "TypeClassification": int(item.get("TypeClassification", 0)),
            "Inflammation": bool(item.get("Inflammation", False)),
            "RootEntryToothFDI": item.get("RootEntryToothFDI", []),
            "Detail": str(item.get("Detail", "")),
            "Confidence_Pneumatization": float(round(item.get("Confidence_Pneumatization", 0.0), 2)),
            "Confidence_Inflammation": float(round(item.get("Confidence_Inflammation", 0.0), 2))
        }
        formatted_list.append(formatted_item)

    logger.info(f"[format_sinus_report] Formatted {len(formatted_list)} sinus results")
    return {"MaxillarySinus": formatted_list}


def format_sinus_anatomy_results(sinus_results: dict) -> List[dict]:
    """
    格式化 AnatomyResults（解剖结构分割掩码）- 上颌窦部分

    注意：此函数需要 pipeline 提供 mask 信息。如果 pipeline 只提供了 bbox，
    则此函数可能无法生成完整的 AnatomyResults。

    Args:
        sinus_results: {
            'MaxillarySinus': [...],
            'masks_info': [
                {
                    "label": "sinus_left",
                    "bbox": [x, y, w, h],
                    "mask": np.array,  # 可选：如果 pipeline 提供了 mask
                    "contour": [...]   # 可选：如果 pipeline 提供了 contour
                },
                ...
            ]
        }

    Returns:
        list: AnatomyResults 列表，包含 sinus_left 和 sinus_right
    """
    anatomy_results = []
    masks_info = sinus_results.get("masks_info", [])

    if not masks_info:
        logger.debug("[format_sinus_anatomy_results] No masks_info found, skipping AnatomyResults")
        return []

    for mask_info in masks_info:
        label = mask_info.get("label", "")
        if not label.startswith("sinus_"):
            continue

        # 提取 mask 和 contour（如果可用）
        mask = mask_info.get("mask", None)
        contour = mask_info.get("contour", [])

        # 如果没有 mask 和 contour，只有 bbox，则无法生成完整的 AnatomyResults
        if mask is None and not contour:
            logger.debug(f"[format_sinus_anatomy_results] No mask/contour for {label}, skipping")
            continue
        
        # 跳过 RLE 生成，避免数据过大导致 Redis Protocol Error
        rle = ""
        
        # 如果没有 contour 但有 mask，尝试从 mask 提取 contour
        if not contour and mask is not None:
            try:
                import cv2
                # 确保 mask 是二值化的 uint8 格式
                if mask.dtype != np.uint8:
                    binary_mask = (mask > 0.5).astype(np.uint8)
                else:
                    binary_mask = mask

                # 提取轮廓
                contours, _ = cv2.findContours(
                    binary_mask,
                    cv2.RETR_EXTERNAL,
                    cv2.CHAIN_APPROX_SIMPLE
                )

                if contours:
                    largest_contour = max(contours, key=cv2.contourArea)
                    coords = largest_contour.squeeze()
                    if coords.ndim == 1:
                        contour = [coords.tolist()]
                    else:
                        contour = coords.tolist()
            except Exception as e:
                logger.warning(f"[format_sinus_anatomy_results] Failed to extract contour from mask: {e}")
                contour = []

        # 获取置信度（从对应的 MaxillarySinus 结果中获取）
        confidence = 0.0
        side = label.replace("sinus_", "")
        maxillary_sinus_list = sinus_results.get("MaxillarySinus", [])
        for item in maxillary_sinus_list:
            if item.get("Side", "") == side:
                # 使用炎症置信度作为整体置信度
                confidence = item.get("Confidence_Inflammation", 0.0)
                break

        anatomy_results.append({
            "Label": label,
            "Confidence": round(confidence, 2),
            "SegmentationMask": {
                "Type": "Polygon",
                "Coordinates": contour if contour else [],
                "SerializedMask": rle
            }
        })

    logger.info(f"[format_sinus_anatomy_results] Generated {len(anatomy_results)} sinus AnatomyResults")
    return anatomy_results


def format_root_tip_density_report(rootTipDensity_results: dict) -> dict:
    """
    格式化根尖低密度影(RootTipDensityAnalysis)部分 - 真实数据

    Args:
        rootTipDensity_results: {
            'density_boxes': [{'box': [...], 'confidence': 0.95, 'quadrant': 1}, ...],
            'quadrant_counts': {1: 2, 2: 0, 3: 1, 4: 0}
        }

    Returns:
        dict: 符合 RootTipDensityAnalysis 格式的字典
    """
    density_boxes = rootTipDensity_results.get("density_boxes", [])
    quadrant_counts = rootTipDensity_results.get("quadrant_counts", {1: 0, 2: 0, 3: 0, 4: 0})

    # 计算总数
    total_count = len(density_boxes)

    # 格式化 Items
    items = []
    for idx, det in enumerate(density_boxes):
        quadrant_id = det.get("quadrant", 0)
        quadrant_name = QUADRANT_MAP.get(quadrant_id, "未知象限")

        items.append({
            "ID": "Low_Density_Lesion",
            "Quadrant": quadrant_name,
            "Confidence": round(det.get("confidence", 0.0), 2),
            "BBox": det.get("box", []),
            "Detail": f"{quadrant_name}检测到根尖低密度影"
        })

    # 生成 Detail 文本
    detail_parts = []
    for quad_id in [1, 2, 3, 4]:
        count = quadrant_counts.get(quad_id, 0)
        if count > 0:
            quad_name = QUADRANT_MAP[quad_id]
            detail_parts.append(f"{quad_name}存在根尖低密度影，个数为{count}")

    detail = "；".join(detail_parts) if detail_parts else "未检测到根尖低密度影"

    # 格式化 QuadrantCounts
    quadrant_counts_formatted = {
        "Q1": quadrant_counts.get(1, 0),
        "Q2": quadrant_counts.get(2, 0),
        "Q3": quadrant_counts.get(3, 0),
        "Q4": quadrant_counts.get(4, 0),
    }

    return {
        "TotalCount": total_count,
        "Items": items,
        "Detail": detail,
        "QuadrantCounts": quadrant_counts_formatted
    }


def _extract_fdi_from_text(text: str) -> str:
    """从文本中提取 FDI 编号，如 "tooth-37 牙位缺牙" -> "37" """
    import re
    match = re.search(r'tooth-(\d+)', text)
    return match.group(1) if match else ""


def _mask_to_rle_fast(mask):
    """
    快速RLE编码（用于segments已存在的情况，只需要编码mask）

    Args:
        mask: [H, W] numpy array (binary mask, 0-1 normalized 或 uint8)

    Returns:
        str: RLE 编码字符串
    """
    return _mask_to_rle(mask)


def _mask_to_rle(mask):
    """
    将二值 mask 转换为 RLE (Run Length Encoding) 格式

    Args:
        mask: [H, W] numpy array (binary mask, 0 或 1)

    Returns:
        str: RLE 编码字符串，格式如 "rle:0,100,1,50,0,200,..."
    """
    try:
        if mask is None:
            return ""

        # 确保是二值mask
        if mask.dtype != np.uint8:
            mask = (mask > 0.5).astype(np.uint8)

        # 展平为一维数组
        flat_mask = mask.flatten()

        if len(flat_mask) == 0:
            return ""

        # RLE编码：记录连续相同值的长度
        rle_data = []
        current_value = flat_mask[0]
        count = 1

        for i in range(1, len(flat_mask)):
            if flat_mask[i] == current_value:
                count += 1
            else:
                rle_data.append(f"{current_value},{count}")
                current_value = flat_mask[i]
                count = 1

        # 添加最后一段
        rle_data.append(f"{current_value},{count}")

        # 格式化为字符串
        rle_string = f"rle:{','.join(rle_data)}"

        return rle_string

    except Exception as e:
        logger.warning(f"Failed to encode RLE: {e}")
        return ""


def _extract_mask_contour_fallback(mask, original_shape):
    """
    从 YOLO 输出的 mask 中提取轮廓坐标（降级方案，仅在segments不可用时使用）

    注意：YOLO的masks已经是原始图像尺寸，不需要resize。
    此函数仅作为segments不可用时的降级方案。

    Args:
        mask: [H, W] numpy array (binary mask, 0-1 normalized，已经是原始图像尺寸)
        original_shape: (H, W) 原始图像尺寸（用于验证，实际不需要resize）

    Returns:
        tuple: (coordinates, serialized_mask)
            - coordinates: [[x, y], ...] 轮廓坐标列表
            - serialized_mask: RLE 编码字符串
    """
    import cv2
    import numpy as np

    try:
        # 1. 确保 mask 是二值化的 uint8 格式
        if mask.dtype != np.uint8:
            # YOLO 输出的 mask 可能是 float [0, 1]
            binary_mask = (mask > 0.5).astype(np.uint8)
        else:
            binary_mask = mask

        # 2. 如果 mask 尺寸与原始图像不同，需要 resize
        # 虽然YOLO的masks通常是原始图像尺寸，但如果确实不匹配，必须resize以确保坐标正确
        if binary_mask.shape != original_shape:
            logger.warning(
                f"Mask shape {binary_mask.shape} != original_shape {original_shape}. "
                f"Resizing mask to match original image size."
            )
            binary_mask = cv2.resize(
                binary_mask,
                (original_shape[1], original_shape[0]),  # (W, H)
                interpolation=cv2.INTER_NEAREST
            )

        # 3. 提取轮廓
        contours, _ = cv2.findContours(
            binary_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE
        )

        # 4. 取最大轮廓并转换为坐标列表
        coordinates = []
        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            # 转换为 [[x, y], [x, y], ...] 格式
            coords = largest_contour.squeeze()

            # 处理只有一个点的情况
            if coords.ndim == 1:
                coordinates = [coords.tolist()]
            else:
                coordinates = coords.tolist()
        
        # 5. 跳过 RLE 编码，避免数据过大导致 Redis Protocol Error
        serialized_mask = ""
        
        return coordinates, serialized_mask

    except Exception as e:
        logger.warning(f"Failed to extract contour: {e}")
        return [], ""


# =============================================================================
# 3. Mock 数据模板
# =============================================================================

def _format_metadata(meta: dict) -> dict:
    return {
        "ImageName": meta.get("ImageName", ""),
        "DiagnosisID": meta.get("DiagnosisID", ""),
        "AnalysisTime": meta.get("AnalysisTime", datetime.datetime.now().isoformat())
    }


def _get_anatomy_results_mock() -> List[dict]:
    """Mock: AnatomyResults - 无模型支持"""
    return []


def _get_joint_mandible_default() -> dict:
    """JointAndMandible 默认值（部分真实，部分默认）"""
    return {
        "CondyleAssessment": {
            "condyle_Left": {
                "Morphology": 0,
                "Detail": "髁突形态正常",
                "Confidence": 0.0
            },
            "condyle_Right": {
                "Morphology": 0,
                "Detail": "髁突形态正常",
                "Confidence": 0.0
            },
            "OverallSymmetry": 0,
            "Confidence_Overall": 0.0
        },
        "RamusSymmetry": False,
        "GonialAngleSymmetry": True,
        "Detail": "",
        "Confidence": 0.0
    }


def _get_maxillary_sinus_mock() -> List[dict]:
    """Mock: MaxillarySinus - 无模型支持"""
    return [
        {
            "Side": "left",
            "Pneumatization": 0,  # 0=正常, 1=轻度气化, 2=过度气化
            "TypeClassification": 0,  # 0, 1 数字类型
            "Inflammation": False,
            "RootEntryToothFDI": [],
            "Detail": "左上颌窦气化正常（待检测）",
            "Confidence_Pneumatization": 0.0,
            "Confidence_Inflammation": 0.0
        },
        {
            "Side": "right",
            "Pneumatization": 0,
            "TypeClassification": 0,
            "Inflammation": False,
            "RootEntryToothFDI": [],
            "Detail": "右上颌窦气化正常（待检测）",
            "Confidence_Pneumatization": 0.0,
            "Confidence_Inflammation": 0.0
        }
    ]


def _get_periodontal_mock() -> dict:
    """Mock: PeriodontalCondition - 无模型支持"""
    return {
        "BoneAbsorptionLevel": 0,
        "Detail": "未检测（需专门牙周模型）",
        "Confidence": 0.0,
        "AbsorptionRatio": 0.0,
        "SpecificAbsorption": []
    }


def _get_implant_default() -> dict:
    """ImplantAnalysis 默认值（真实数据会覆盖）"""
    return {
        "TotalCount": 0,
        "Items": [],
        "Detail": "未检测到种植体",
        "QuadrantCounts": {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}
    }


def _get_root_tip_density_default() -> dict:
    """RootTipDensityAnalysis 默认值（真实数据会覆盖）"""
    return {
        "TotalCount": 0,
        "Items": [],
        "Detail": "未检测到根尖低密度影",
        "QuadrantCounts": {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}
    }
