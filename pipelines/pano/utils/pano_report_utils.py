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


# =============================================================================
# 1. 核心对外接口
# =============================================================================

def generate_standard_output(
        metadata: Dict[str, Any],
        inference_results: Dict[str, Any]
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
    rootTipDensity_res = inference_results.get("rootTipDensity", {})

    # 1. 初始化基础骨架（严格按照 example_pano_result.json 顺序）
    report = {
        "Metadata": _format_metadata(metadata),
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
        teeth_data = format_teeth_report(teeth_res)
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


def format_teeth_report(teeth_results: dict) -> dict:
    """
    格式化牙齿(Teeth)部分 - 真实数据
    
    Args:
        teeth_results: {
            'report': str,
            'missing_teeth': [...],
            'wisdom_teeth': [...],
            'deciduous_teeth': [...],
            'detected_teeth': [{'fdi': str, 'class_name': str, 'mask_index': int}, ...],
            'raw_masks': np.ndarray,  # [N, H, W] (已经是原始图像尺寸)
            'segments': np.ndarray,  # [N, num_points, 2] 多边形坐标（原始图像坐标）
            'original_shape': tuple  # (H, W)
        }
    
    Returns:
        dict: 包含 MissingTeeth, ThirdMolarSummary, ToothAnalysis
    """
    missing_teeth_raw = teeth_results.get("missing_teeth", [])
    wisdom_teeth_raw = teeth_results.get("wisdom_teeth", [])
    deciduous_teeth_raw = teeth_results.get("deciduous_teeth", [])
    detected_teeth_list = teeth_results.get("detected_teeth", [])
    raw_masks = teeth_results.get("raw_masks", None)
    segments = teeth_results.get("segments", None)  # 直接从YOLO获取的多边形坐标
    original_shape = teeth_results.get("original_shape", None)
    
    # 1. 格式化 MissingTeeth
    missing_teeth = []
    for item in missing_teeth_raw:
        fdi = _extract_fdi_from_text(item)
        if fdi:
            missing_teeth.append({
                "FDI": fdi,
                "Reason": "missing",
                "Detail": item
            })
    
    # 2. 格式化 ThirdMolarSummary (根据真实检测结果填充)
    third_molar_summary = {}
    
    # 从 detected_teeth_list 中提取智齿FDI
    detected_wisdom_fdi = set()
    for tooth_info in detected_teeth_list:
        fdi = tooth_info.get("fdi", "")
        if fdi in WISDOM_TEETH_FDI:
            detected_wisdom_fdi.add(fdi)
    
    # 填充所有智齿位置
    for fdi in WISDOM_TEETH_FDI:
        if fdi in detected_wisdom_fdi:
            # 检测到智齿：Level=1 (阻生), Impactions="Impacted"
            third_molar_summary[fdi] = {
                "Level": 1,
                "Impactions": "Impacted",
                "Detail": "阻生",
                "Confidence": 0.85
            }
        else:
            # 未检测到智齿：Level=4 (未见智齿), Impactions=None
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
        
        # 构建属性列表
        properties = []
        
        # 判断是否是智齿
        if fdi in WISDOM_TEETH_FDI:
            properties.append({
                "Value": "Impacted",
                "Description": "阻生",
                "Confidence": 0.85
            })
        
        # 判断是否是乳牙滞留
        if fdi in DECIDUOUS_TEETH_FDI:
            properties.append({
                "Value": "retained_primary_tooth",
                "Description": "滞留乳牙",
                "Confidence": 0.85
            })
        
        # 提取轮廓坐标：使用YOLO直接输出的segments（格式: [N, num_points, 2]）
        # 目标格式: [[x, y], [x, y], ...] 符合前端期望和规范
        coordinates = []
        serialized_mask = ""
        
        import numpy as np
        
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
            "Properties": properties  # 空列表表示正常牙齿，有内容表示有特殊属性
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
