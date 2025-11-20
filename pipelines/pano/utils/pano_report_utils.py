# -*- coding: utf-8 -*-
"""
全景片报告生成工具 (Assembler) - 接口严格对齐版
"""

import logging
import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)

# =============================================================================
# 0. 常量与映射
# =============================================================================

MORPHOLOGY_MAP = {
    0: {"detail": "髁突形态正常", "label": "正常"},
    1: {"detail": "髁突形态吸收", "label": "吸收"},
    2: {"detail": "髁突形态疑似异常", "label": "疑似"},
}


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
    """
    # 1. 初始化基础骨架 (严格按照接口定义顺序)
    report = {
        "Metadata": _format_metadata(metadata),
        "AnatomyResults": [],  # TODO: 等牙齿模块集成
        "JointAndMandible": _get_joint_mandible_default(),
        "MaxillarySinus": [],  # 格式确认但无模型，先空数组
        "PeriodontalCondition": _get_periodontal_default(),  # TODO: 等牙齿模块集成
        "MissingTeeth": [],  # TODO: 等牙齿模块集成
        "ThirdMolarSummary": {},  # TODO: 等牙齿模块集成
        "ImplantAnalysis": _get_implant_default(),  # TODO: 等种植体模块集成
        "ToothAnalysis": []  # TODO: 等牙齿模块集成
    }

    # 2. 组装髁突部分 (CondyleAssessment)
    # 合并 condyle_seg 和 condyle_det 的结果
    condyle_seg = inference_results.get("condyle_seg", {})
    condyle_det = inference_results.get("condyle_det", {})
    
    if condyle_seg or condyle_det:
        condyle_data = format_joint_report(condyle_seg, condyle_det)
        # 只更新 CondyleAssessment 部分，不覆盖下颌骨字段
        report["JointAndMandible"]["CondyleAssessment"] = condyle_data["CondyleAssessment"]

    # 3. 组装下颌骨部分 (Mandible - 升支/下颌角部分)
    mandible_res = inference_results.get("mandible", {})
    if mandible_res and "analysis" in mandible_res:
        mandible_data = format_mandible_report(mandible_res["analysis"])
        
        # 合并下颌骨数据，注意 Detail 的拼接
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

    return report


# =============================================================================
# 2. 格式化函数 (Predictor 调用)
# =============================================================================

def format_joint_report(condyle_seg: dict, condyle_det: dict) -> dict:
    """
    格式化髁突(Condyle)部分
    
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
    
    # 调试日志：检查检测模块的置信度
    logger.debug(f"[format_joint_report] Detection confidence - Left: {left_conf_det}, Right: {right_conf_det}")
    
    # 获取分割结果中的置信度和存在性
    seg_features = condyle_seg.get("raw_features", {})
    seg_left = seg_features.get("left", {})
    seg_right = seg_features.get("right", {})
    
    left_exists = seg_left.get("exists", False)
    right_exists = seg_right.get("exists", False)
    left_conf_seg = seg_left.get("confidence", 0.0)
    right_conf_seg = seg_right.get("confidence", 0.0)
    
    # 调试日志：检查分割模块的置信度
    logger.debug(f"[format_joint_report] Segmentation confidence - Left: {left_conf_seg} (exists: {left_exists}), Right: {right_conf_seg} (exists: {right_exists})")
    
    # 综合置信度 (取检测和分割的平均值)
    # 注意：如果分割模块检测到了，则取两个模块的平均值；否则只用检测模块的置信度
    if left_exists and left_conf_seg > 0:
        left_confidence = (left_conf_det + left_conf_seg) / 2
    else:
        left_confidence = left_conf_det
    
    if right_exists and right_conf_seg > 0:
        right_confidence = (right_conf_det + right_conf_seg) / 2
    else:
        right_confidence = right_conf_det
    
    # 调试日志：检查综合置信度
    logger.debug(f"[format_joint_report] Final confidence - Left: {left_confidence}, Right: {right_confidence}")
    
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
    # 确保置信度始终为浮点数格式（保留2位小数）
    condyle_assessment = {
        "condyle_Left": {
            "Morphology": left_morphology,
            "IsSymmetrical": is_symmetric,
            "Detail": left_detail,
            "Confidence": float(round(left_confidence, 2))
        },
        "condyle_Right": {
            "Morphology": right_morphology,
            "IsSymmetrical": is_symmetric,
            "Detail": right_detail,
            "Confidence": float(round(right_confidence, 2))
        },
        "OverallSymmetry": overall_symmetry,
        "Confidence_Overall": float(round(max(left_confidence, right_confidence), 2))
    }
    
    return {"CondyleAssessment": condyle_assessment}


def format_mandible_report(analysis_result: dict) -> dict:
    """
    【严格对齐检查】格式化下颌骨(Mandible)部分
    对应接口中的 JointAndMandible 下半部分
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
    【严格对齐检查】格式化种植体(Implant)部分
    对应接口中的 ImplantAnalysis
    """
    analysis = implant_results.get("analysis", {})
    detections = implant_results.get("raw_detections", [])  # 注意这里取 raw_detections
    summary = implant_results.get("summary", {})

    # 映射象限
    quad_map_key = {"第一象限": "Q1", "第二象限": "Q2", "第三象限": "Q3", "第四象限": "Q4"}
    raw_counts = summary.get("quadrant_counts", {})

    formatted_counts = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}
    for k, v in raw_counts.items():
        if k in quad_map_key:
            formatted_counts[quad_map_key[k]] = v

    # 映射 Items
    items = []
    for det in detections:
        # det 结构来自 ImplantDetector: {id, bbox, confidence, quadrant}
        items.append({
            "ID": det.get("id"),
            "Quadrant": det.get("quadrant", "未知"),
            "Confidence": det.get("confidence", 0.0),
            "BBox": det.get("bbox", []),
            "Detail": f"{det.get('quadrant')}检测到种植体"
        })

    return {
        "TotalCount": summary.get("total_count", 0),
        "Detail": summary.get("text", "未检测到种植体"),
        "QuadrantCounts": formatted_counts,
        "Items": items
    }


# =============================================================================
# 3. 默认值模板 (Skeleton)
# =============================================================================

def _format_metadata(meta: dict) -> dict:
    return {
        "ImageName": meta.get("ImageName", ""),
        "DiagnosisID": meta.get("DiagnosisID", ""),
        "AnalysisTime": meta.get("AnalysisTime", datetime.datetime.now().isoformat())
    }


def _get_joint_mandible_default() -> dict:
    """
    对应接口中的 JointAndMandible
    包含 CondyleAssessment (髁突) 和 Ramus/Gonial (下颌骨)
    """
    return {
        "CondyleAssessment": {
            "condyle_Left": {
                "Morphology": 0, 
                "IsSymmetrical": False, 
                "Detail": "髁突形态正常", 
                "Confidence": 0.0
            },
            "condyle_Right": {
                "Morphology": 0, 
                "IsSymmetrical": False, 
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


def _get_implant_default() -> dict:
    """
    【新增】对应接口中的 ImplantAnalysis
    """
    return {
        "TotalCount": 0,
        "Detail": "未检测到种植体",
        "QuadrantCounts": {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0},
        "Items": []
    }


def _get_periodontal_default() -> dict:
    return {
        "CEJ_to_ABC_Distance_mm": 0.0,
        "BoneAbsorptionLevel": 0,
        "Detail": "未检测",
        "AbsorptionRatio": 0.0,
        "Confidence": 0.0
    }