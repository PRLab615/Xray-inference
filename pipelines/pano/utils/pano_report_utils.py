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
    """
    # 1. 初始化基础骨架 (严格按照接口定义顺序)
    report = {
        "Metadata": _format_metadata(metadata),
        "AnatomyResults": [],
        "JointAndMandible": _get_joint_mandible_default(),  # 合并了关节和下颌骨默认值
        "MaxillarySinus": [],
        "PeriodontalCondition": _get_periodontal_default(),
        "MissingTeeth": [],
        "ThirdMolarSummary": {},
        "ImplantAnalysis": _get_implant_default(),  # 【新增】确保种植体字段存在
        "ToothAnalysis": []
    }

    # 2. 组装关节 (Joint - 髁突部分)
    if "joint" in inference_results:
        joint_res = inference_results["joint"]
        if "standard_data" in joint_res:
            # 注意：这里是一个深度合并的过程，不能直接覆盖，否则会弄丢下颌骨的数据
            # 但由于我们是分步填充，这里假设 joint_res 只包含 CondyleAssessment 部分
            # 更稳健的做法是 update
            report["JointAndMandible"].update(joint_res["standard_data"])

    # 3. 组装下颌骨 (Mandible - 升支/下颌角部分)
    if "mandible" in inference_results:
        mandible_res = inference_results["mandible"]
        if "mandible_standard_data" in mandible_res:
            # 将下颌骨数据合并进去 (RamusSymmetry, GonialAngleSymmetry, Detail...)
            # 注意 Detail 需要拼接
            existing_detail = report["JointAndMandible"].get("Detail", "")
            new_detail = mandible_res["mandible_standard_data"].get("Detail", "")

            report["JointAndMandible"].update(mandible_res["mandible_standard_data"])

            # 拼接 Detail 描述
            if existing_detail and new_detail:
                report["JointAndMandible"]["Detail"] = f"{existing_detail}；{new_detail}"
            elif new_detail:
                report["JointAndMandible"]["Detail"] = new_detail

    # 4. 组装种植体 (Implant)
    if "implant" in inference_results:
        implant_res = inference_results["implant"]
        # 假设 implant predictor 返回了 standard_data
        if "standard_data" in implant_res:
            report["ImplantAnalysis"] = implant_res["standard_data"]

    return report


# =============================================================================
# 2. 格式化函数 (Predictor 调用)
# =============================================================================

def format_joint_report(raw_features: dict, analysis: dict) -> dict:
    """格式化髁突(Condyle)部分"""
    SYM_NORMAL, SYM_LEFT_BIG, SYM_RIGHT_BIG = 0, 1, 2

    # 获取默认结构
    joint_data = _get_joint_mandible_default()  # 包含完整的 JointAndMandible 结构

    # ... (此处省略之前已确认正确的提取置信度、形态学逻辑，保持不变) ...
    # 简写以展示结构：
    left = raw_features.get("left", {})
    right = raw_features.get("right", {})

    # 填充 CondyleAssessment
    # ... (逻辑同前) ...

    # 填充 OverallSymmetry
    # ... (逻辑同前) ...

    # 返回的只是 JointAndMandible 的结构，Predictor 会把它放在 standard_data 里
    return joint_data


def format_mandible_report(analysis_result: dict) -> dict:
    """
    【严格对齐检查】格式化下颌骨(Mandible)部分
    对应接口中的 JointAndMandible 下半部分
    """
    return {
        "RamusSymmetry": bool(analysis_result.get("RamusSymmetry", False)),
        "GonialAngleSymmetry": bool(analysis_result.get("GonialAngleSymmetry", False)),
        "Detail": str(analysis_result.get("Detail", "未检测到下颌骨结构")),
        "Confidence": float(analysis_result.get("Confidence", 0.0))
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
            "condyle_Left": {"Morphology": 0, "IsSymmetrical": True, "Detail": "未见明显异常", "Confidence": 0.0},
            "condyle_Right": {"Morphology": 0, "IsSymmetrical": True, "Detail": "未见明显异常", "Confidence": 0.0},
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