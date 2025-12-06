# -*- coding: utf-8 -*-
"""侧位片报告生成工具：将推理结果格式化为规范 JSON。"""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from statistics import mean
from typing import Any, Dict, List, Union

import numpy as np

from .ceph_report import (
    KEYPOINT_MAP,
    ANB_SKELETAL_II_THRESHOLD,
    ANB_SKELETAL_III_THRESHOLD,
    FH_MP_HIGH_ANGLE_THRESHOLD,
    FH_MP_LOW_ANGLE_THRESHOLD,
    SGO_NME_HORIZONTAL_THRESHOLD,
    SGO_NME_VERTICAL_THRESHOLD,
    DEFAULT_SPACING_MM_PER_PIXEL,
)

logger = logging.getLogger(__name__)

# 关键点简称到完整名称的映射（用于输出）
LABEL_FULL_NAMES = {
    "S": "Sella",
    "N": "Nasion",
    "Or": "Orbitale",
    "Po": "Porion",
    "A": "Subspinale",
    "B": "Supramentale",
    "Pog": "Pogonion",
    "Me": "Menton",
    "Gn": "Gnathion",
    "Go": "Gonion",
    "L1": "Incision inferius",
    "UI": "Incision superius",
    "Bo": "Bo",
    "Pt": "Pt",
    "ANS": "Anterior nasal spine",
    "PNS": "Posterior nasal spine",
    "Ar": "Articulare",
    "Ba": "Ba",
    "Co": "Co",
    "PTM": "PTM",
    "U6": "U6",
    "L6": "L6",
    "U1A": "U1A",
    "L1A": "L1A",
    "Pcd": "Pcd",
}

MEASUREMENT_ORDER = [
    "ANB_Angle",
    "PtmANS_Length",
    "GoPo_Length",
    "PoNB_Length",
    "Jaw_Development_Coordination",
    "SGo_NMe_Ratio",
    "FH_MP_Angle",
    "IMPA_Angle",
    "Airway_Gap",                    # 可选
    "Adenoid_Index",                 # 可选
    "SNA_Angle",
    "Upper_Jaw_Position",
    "SNB_Angle",
    "Pcd_Lower_Position",
    "Distance_Witsmm",
    "U1_SN_Angle",
    "U1_NA_Angle",
    "U1_NA_Incisor_Length",
    "FMIA_Angle",
    "L1_NB_Angle",
    "L1_NB_Distance",
    "U1_L1_Inter_Incisor_Angle",
    "Y_Axis_Angle",                  # ㉗ Y轴角（原 Y_SGo_NMe_Ratio-2，已修正命名）
    "Mandibular_Growth_Angle",
    "SN_MP_Angle",                   # ㉚ SN-MP角（原 SN_FH_Angle-1，已修正命名）
    "U1_PP_Upper_Anterior_Alveolar_Height",
    "L1_MP_Lower_Anterior_Alveolar_Height",
    "U6_PP_Upper_Posterior_Alveolar_Height",
    "L6_MP_Lower_Posterior_Alveolar_Height",
    "Mandibular_Growth_Type_Angle",  # Björk sum
    "S_N_Anterior_Cranial_Base_Length",
    "Go_Me_Length",
    "Cervical_Vertebral_Maturity_Stage",  # 可选
]

# 特殊测量项类型定义
MULTISELECT_MEASUREMENTS = {"Jaw_Development_Coordination"}
AIRWAY_MEASUREMENTS = {"Airway_Gap"}
BOOLEAN_LEVEL_MEASUREMENTS = {"Airway_Gap", "Adenoid_Index"}
CERVICAL_VERTEBRAL_MEASUREMENTS = {"Cervical_Vertebral_Maturity_Stage"}

# 未检测标识：Level=-1 表示该测量项未被模型检测到
UNDETECTED_LEVEL = -1


def generate_standard_output(
    inference_results: Dict[str, Any],
    patient_info: Dict[str, str],
) -> Dict[str, Any]:
    """
    将推理结果映射为符合《接口定义.md》的 data 字段。
    
    Args:
        inference_results: 推理结果，包含 landmarks, measurements, spacing
        patient_info: 患者信息
        
    Returns:
        符合规范的 data 字段
        
    注意：
        spacing 已由 point_model.run() 处理并放入 inference_results["spacing"]
        优先级为：DICOM/请求参数 > patient_info["PixelSpacing"] > 默认值
    """
    landmarks_block = inference_results.get("landmarks", {})
    measurements = inference_results.get("measurements", {})
    
    # 从推理结果获取实际使用的 spacing，如果没有则使用默认值
    spacing = inference_results.get("spacing", DEFAULT_SPACING_MM_PER_PIXEL)

    landmark_section = _build_landmark_section(landmarks_block)
    measurement_section = _build_measurement_section_in_order(measurements)

    visibility_grade = _visibility_grade(
        landmark_section["DetectedLandmarks"], landmark_section["TotalLandmarks"]
    )
    average_confidence = landmark_section.get("AverageConfidence", 0.0)

    data_dict = {
        "ImageSpacing": {
            "X": spacing,
            "Y": spacing,
            "Unit": "mm/pixel",
        },
        "VisibilityMetrics": {
            "Grade": visibility_grade,
            "MissingLandmarks": landmark_section["MissingLabels"],
        },
        "MissingPointHandling": {
            "Method": "插值估算",
            "ConfidenceThreshold": 0.7,
            "InterpolationAllowed": False,
        },
        "StatisticalFields": {
            "ProcessedLandmarks": landmark_section["DetectedLandmarks"],
            "MissingLandmarks": landmark_section["MissingLandmarks"],
            "AverageConfidence": round(average_confidence, 2),
            "QualityScore": round(average_confidence, 2),
        },
        "PatientInformation": {
            "Gender": patient_info.get("Gender", "Male"),
            "DentalAgeStage": {
                "CurrentStage": patient_info.get("DentalAgeStage", "Permanent"),
            },
        },
        "LandmarkPositions": {
            "TotalLandmarks": landmark_section["TotalLandmarks"],
            "DetectedLandmarks": landmark_section["DetectedLandmarks"],
            "MissingLandmarks": landmark_section["MissingLandmarks"],
            "Landmarks": landmark_section["Landmarks"],
        },
        "CephalometricMeasurements": {
            "AllMeasurements": measurement_section,
        },
    }

    logger.info(
        "Generated cephalometric JSON: %s/%s landmarks,%s measurements",
        landmark_section["DetectedLandmarks"],
        landmark_section["TotalLandmarks"],
        len(measurement_section),
    )
    return data_dict


def _build_landmark_section(landmarks_block: Dict[str, Any]) -> Dict[str, Any]:
    coordinates: Dict[str, Any] = landmarks_block.get("coordinates", {})
    confidences: Dict[str, float] = landmarks_block.get("confidences", {})

    entries: List[Dict[str, Any]] = []
    detected = 0
    missing_labels: List[str] = []
    confidence_values: List[float] = []

    for key, short_label in KEYPOINT_MAP.items():
        # 使用完整标签名
        full_label = LABEL_FULL_NAMES.get(short_label, short_label)
        
        coord = coordinates.get(key)
        confidence = confidences.get(key, 0.0)

        x_value = float(coord[0]) if _is_valid_point(coord) else None
        y_value = float(coord[1]) if _is_valid_point(coord) else None
        status = "Detected" if x_value is not None and y_value is not None else "Missing"

        if status == "Detected":
            detected += 1
            confidence_values.append(confidence)
        else:
            missing_labels.append(full_label)

        # 格式化置信度：Detected 时保留两位小数，Missing 时为 0.00
        formatted_confidence = round(confidence, 2) if status == "Detected" else 0.00

        entries.append(
            {
                "Label": full_label,
                "X": int(x_value) if x_value is not None else None,
                "Y": int(y_value) if y_value is not None else None,
                "Confidence": formatted_confidence,
                "Status": status,
            }
        )

    total = len(KEYPOINT_MAP)
    average_confidence = round(mean(confidence_values), 2) if confidence_values else 0.0

    return {
        "TotalLandmarks": total,
        "DetectedLandmarks": detected,
        "MissingLandmarks": total - detected,
        "Landmarks": entries,
        "MissingLabels": missing_labels,
        "AverageConfidence": average_confidence,
    }


def _build_measurement_section_in_order(measurements: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    关键修改：严格按照 MEASUREMENT_ORDER 顺序输出所有测量项
    缺失的项目也会占位（返回空值但保留Label），保证序号不乱
    """
    section: List[Dict[str, Any]] = []

    for name in MEASUREMENT_ORDER:
        payload = measurements.get(name, {})
        entry = _build_measurement_entry(name, payload)
        section.append(entry)

    return section


def _build_measurement_section(measurements: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    section: List[Dict[str, Any]] = []

    for name, payload in measurements.items():
        entry = _build_measurement_entry(name, payload)
        section.append(entry)

    return section


def _build_measurement_entry(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    根据测量项类型构建对应的输出格式。
    
    支持的类型：
    - 角度测量：{"Label": "...", "Angle": ..., "Level": int, "Confidence": ...}
    - 长度测量：{"Label": "...", "Length_mm": ..., "Level": int, "Confidence": ...}
    - 比率测量：{"Label": "...", "Ratio": ..., "Level": int, "Confidence": ...}
    - 多选类型：{"Label": "...", "Type": "MultiSelect", "Level": [int], "Confidence": ...}
    - 气道测量：{"Label": "...", "PNS-UPW": ..., ..., "Level": bool, "Confidence": ...}
    - 颈椎成熟度：{"Label": "...", "Coordinates": [...], "SerializedMask": "...", "Level": int, "Confidence": ...}
    
    未检测标识：
    - 当 payload 为空或缺少 value 时，Level=-1 表示未检测到
    - 数值字段设为 null，Confidence=0.0
    """
    value = payload.get("value")
    unit = payload.get("unit", "")
    conclusion = payload.get("conclusion")
    confidence = payload.get("confidence", 0.0)
    
    # 判断是否为未检测状态：payload 为空或 value 为 None
    is_undetected = not payload or value is None
    
    # 处理特殊类型
    if name in CERVICAL_VERTEBRAL_MEASUREMENTS:
        return _build_cervical_entry(name, payload)
    
    if name in AIRWAY_MEASUREMENTS:
        return _build_airway_entry(name, payload)
    
    if name in MULTISELECT_MEASUREMENTS:
        return _build_multiselect_entry(name, payload)
    
    # 标准测量项
    entry: Dict[str, Any] = {"Label": name}
    
    # 根据单位确定值字段名
    if unit in ("°", "degrees"):
        entry["Angle"] = _format_value(value)
    elif unit == "mm":
        entry["Length_mm"] = _format_value(value)
    elif unit == "%":
        entry["Ratio"] = _format_value(value)
    else:
        # 根据测量项名称推断类型
        if name.endswith("_Angle") or "Angle" in name:
            entry["Angle"] = _format_value(value)
        elif "Length" in name or "Distance" in name or "Height" in name:
            entry["Length_mm"] = _format_value(value)
        elif "Ratio" in name:
            entry["Ratio"] = _format_value(value)
        else:
            entry["Angle"] = _format_value(value)
    
    # 确定 Level：未检测时使用 UNDETECTED_LEVEL (-1)
    if is_undetected:
        entry["Level"] = UNDETECTED_LEVEL
    elif name in BOOLEAN_LEVEL_MEASUREMENTS:
        entry["Level"] = bool(conclusion) if conclusion is not None else True
    else:
        level = conclusion if conclusion in (0, 1, 2) else 0
        entry["Level"] = int(level)

    entry["Confidence"] = round(float(confidence), 2)

    return entry


def _build_cervical_entry(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建颈椎成熟度测量项。
    
    未检测标识：当 payload 为空或缺少 conclusion 时，Level=-1
    """
    # 判断是否为未检测状态
    is_undetected = not payload or payload.get("conclusion") is None
    
    coordinates = payload.get("coordinates", [])
    serialized_mask = payload.get("serialized_mask", "")
    level = payload.get("conclusion")
    confidence = payload.get("confidence", 0.0)
    
    return {
        "Label": name,
        "Coordinates": coordinates if not is_undetected else [],
        "SerializedMask": serialized_mask if not is_undetected else "",
        "Level": int(level) if level is not None else UNDETECTED_LEVEL,
        "Confidence": round(float(confidence), 2),
    }


def _build_airway_entry(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建气道测量项。
    
    格式：{"Label": "Airway_Gap", "PNS-UPW": ..., "SPP-SPPW": ..., 
           "U-MPW": ..., "TB-YPPW": ..., "V-LPW": ..., "Level": bool, "Confidence": ...}
    
    未检测标识：当 payload 为空时，所有气道值为 null，Level=null（而非 true/false）
    """
    entry: Dict[str, Any] = {"Label": name}
    
    # 判断是否为未检测状态
    is_undetected = not payload
    
    # 提取各个气道距离值
    airway_keys = ["PNS-UPW", "SPP-SPPW", "U-MPW", "TB-YPPW", "V-LPW"]
    has_any_value = False
    
    for key in airway_keys:
        if key in payload:
            entry[key] = _format_value(payload[key])
            if entry[key] is not None:
                has_any_value = True
    
    # 如果没有单独字段，尝试从 value 中提取
    value = payload.get("value")
    if isinstance(value, dict):
        for key in airway_keys:
            if key in value:
                entry[key] = _format_value(value[key])
                if entry[key] is not None:
                    has_any_value = True
    
    # 未检测时 Level 设为 null（前端可据此判断）
    if is_undetected or not has_any_value:
        entry["Level"] = None
    else:
        # 气道测量的 Level 为 bool，根据 conclusion 或默认 True
        conclusion = payload.get("conclusion")
        entry["Level"] = bool(conclusion) if conclusion is not None else True
    
    entry["Confidence"] = round(float(payload.get("confidence", 0.0)), 2)
    
    return entry


def _build_multiselect_entry(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建多选类型测量项。
    
    格式：{"Label": "...", "Type": "MultiSelect", "Level": [int], "Confidence": ...}
    
    未检测标识：当 payload 为空或 conclusion 为 None 时，Level=[-1]
    """
    # 判断是否为未检测状态
    is_undetected = not payload or payload.get("conclusion") is None
    
    conclusion = payload.get("conclusion")
    confidence = payload.get("confidence", 0.0)
    
    # Level 为数组形式，未检测时使用 [-1]
    if is_undetected:
        level = [UNDETECTED_LEVEL]
    elif isinstance(conclusion, list):
        level = [int(x) for x in conclusion]
    else:
        level = [int(conclusion)]
    
    return {
        "Label": name,
        "Type": "MultiSelect",
        "Level": level,
        "Confidence": round(float(confidence), 2),
    }


def _format_value(value: Any) -> Union[float, None]:
    """
    格式化数值，保留两位小数。
    
    使用 Decimal 避免浮点数精度问题：
    - 保留两位小数可以更清晰地显示实际测量值（如 112.05° 而不是 112.0°）
    - 使用 ROUND_HALF_UP 标准四舍五入（而非 Python 默认的银行家舍入）
    """
    if value is None:
        return None
    try:
        # 转为 Decimal 进行精确舍入（保留两位小数），再转回 float
        return float(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    except (ValueError, TypeError, Exception):
        return None


def _get_measurement_level(name: str, conclusion: Any, value: Any) -> int:
    """
    根据测量项结论确定Level值。
    
    conclusion 现在已经是 level (int) 了，直接返回。
    如果 conclusion 无效，则根据 value 和 name 重新计算。
    
    Level编码规则：
    - 0: 正常/骨性I类/均角/平均生长型
    - 1: 异常偏高/骨性II类/高角/水平生长型
    - 2: 异常偏低/骨性III类/低角/垂直生长型
    """
    # 首先尝试使用 conclusion
    if conclusion is not None:
        # 如果是布尔值，直接忽略（布尔值不应该作为 level）
        if isinstance(conclusion, bool):
            logger.warning(f"测量项 {name}: conclusion 是布尔值 {conclusion}，将忽略并使用 value 重新计算")
        else:
            try:
                # 处理 numpy 类型：先转换为 Python 原生类型
                if hasattr(conclusion, 'item'):  # numpy 标量类型有 item() 方法
                    conclusion = conclusion.item()
                level = int(conclusion)
                # 确保 level 在有效范围内，并返回 Python 原生 int
                if level in (0, 1, 2):
                    return int(level)
                else:
                    logger.warning(f"测量项 {name}: conclusion={level} 不在有效范围 (0-2)，将使用 value 重新计算")
            except (ValueError, TypeError) as e:
                logger.warning(f"测量项 {name}: 无法将 conclusion={conclusion} (type={type(conclusion).__name__}) 转换为 int: {e}，将使用 value 重新计算")
    
    # 如果 conclusion 无效，根据 value 和 name 重新计算
    if value is None:
        return 0
    
    try:
        num_value = float(value)
        
        # ANB角：骨性I类=0, 骨性II类=1, 骨性III类=2
        if name == "ANB_Angle":
            if num_value > ANB_SKELETAL_II_THRESHOLD:
                return 1  # 骨性II类
            if num_value < ANB_SKELETAL_III_THRESHOLD:
                return 2  # 骨性III类
            return 0  # 骨性I类
        
        # 下颌平面角(FH_MP_Angle)：均角=0, 高角=1, 低角=2
        if name == "FH_MP_Angle":
            if num_value > FH_MP_HIGH_ANGLE_THRESHOLD:
                return 1  # 高角
            if num_value < FH_MP_LOW_ANGLE_THRESHOLD:
                return 2  # 低角
            return 0  # 均角
        
        # 面部高度比例(SGo_NMe_Ratio)：平均生长型=0, 水平生长型=1, 垂直生长型=2
        if name.startswith("SGo_NMe_Ratio"):
            if num_value > SGO_NME_HORIZONTAL_THRESHOLD:
                return 1  # 水平生长型
            if num_value < SGO_NME_VERTICAL_THRESHOLD:
                return 2  # 垂直生长型
            return 0  # 平均生长型
    except (ValueError, TypeError):
        pass
    
    # 默认返回 0
    return 0


def _visibility_grade(detected: int, total: int) -> str:
    if total == 0:
        return "Unknown"
    ratio = detected / total
    if ratio >= 0.9:
        return "Excellent"
    if ratio >= 0.75:
        return "Good"
    if ratio >= 0.5:
        return "Fair"
    return "Poor"


def _is_valid_point(point: Any) -> bool:
    if point is None:
        return False
    point_np = np.asarray(point, dtype=float)
    return not np.isnan(point_np).any()
