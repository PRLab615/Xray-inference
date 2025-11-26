# -*- coding: utf-8 -*-
"""侧位片报告生成工具：将推理结果格式化为规范 JSON。"""

from __future__ import annotations

import logging
from statistics import mean
from typing import Any, Dict, List

import numpy as np

from .ceph_report import (
    KEYPOINT_MAP,
    ANB_SKELETAL_II_THRESHOLD,
    ANB_SKELETAL_III_THRESHOLD,
    FH_MP_HIGH_ANGLE_THRESHOLD,
    FH_MP_LOW_ANGLE_THRESHOLD,
    SGO_NME_HORIZONTAL_THRESHOLD,
    SGO_NME_VERTICAL_THRESHOLD,
)

logger = logging.getLogger(__name__)

def generate_standard_output(
    inference_results: Dict[str, Any],
    patient_info: Dict[str, str],
) -> Dict[str, Any]:
    """
    将推理结果映射为符合《接口定义.md》的 data 字段。
    """
    landmarks_block = inference_results.get("landmarks", {})
    measurements = inference_results.get("measurements", {})

    landmark_section = _build_landmark_section(landmarks_block)
    measurement_section = _build_measurement_section(measurements)

    visibility_grade = _visibility_grade(
        landmark_section["DetectedLandmarks"], landmark_section["TotalLandmarks"]
    )
    average_confidence = landmark_section.get("AverageConfidence", 0.0)

    data_dict = {
        "ImageSpacing": {
            "X": 0.0,
            "Y": 0.0,
            "Unit": "mm/pixel",
        },
        "VisibilityMetrics": {
            "Grade": visibility_grade,
            "MissingLandmarks": landmark_section["MissingLabels"],
        },
        "MissingPointHandling": {
            "Method": "插值估算",
            "ConfidenceThreshold": 0.15,
            "InterpolationAllowed": False,
        },
        "StatisticalFields": {
            "ProcessedLandmarks": landmark_section["DetectedLandmarks"],
            "MissingLandmarks": landmark_section["MissingLandmarks"],
            "AverageConfidence": average_confidence,
            "QualityScore": round(average_confidence * 100, 2),
        },
        "PatientInformation": {
            "Gender": patient_info.get("gender", ""),
            "DentalAgeStage": {
                "CurrentStage": patient_info.get("DentalAgeStage", ""),
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
        "Generated cephalometric JSON: %s/%s landmarks",
        landmark_section["DetectedLandmarks"],
        landmark_section["TotalLandmarks"],
    )
    return data_dict

def _build_landmark_section(landmarks_block: Dict[str, Any]) -> Dict[str, Any]:
    coordinates: Dict[str, Any] = landmarks_block.get("coordinates", {})
    confidences: Dict[str, float] = landmarks_block.get("confidences", {})

    entries: List[Dict[str, Any]] = []
    detected = 0
    missing_labels: List[str] = []
    confidence_values: List[float] = []

    for key, label in KEYPOINT_MAP.items():
        coord = coordinates.get(key)
        confidence = confidences.get(key, 0.0)

        x_value = float(coord[0]) if _is_valid_point(coord) else None
        y_value = float(coord[1]) if _is_valid_point(coord) else None
        status = "Detected" if x_value is not None and y_value is not None else "Missing"

        if status == "Detected":
            detected += 1
            confidence_values.append(confidence)
        else:
            missing_labels.append(label)

        entries.append(
            {
                "Label": label,
                "X": x_value,
                "Y": y_value,
                "Confidence": 0.00 if status == "Missing" else round(confidence, 4),
                "Status": status,
            }
        )

    total = len(KEYPOINT_MAP)
    average_confidence = round(mean(confidence_values), 4) if confidence_values else 0.0

    return {
        "TotalLandmarks": total,
        "DetectedLandmarks": detected,
        "MissingLandmarks": total - detected,
        "Landmarks": entries,
        "MissingLabels": missing_labels,
        "AverageConfidence": average_confidence,
    }

def _build_measurement_section(measurements: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    section: List[Dict[str, Any]] = []

    for name, payload in measurements.items():
        value = payload.get("value")
        unit = payload.get("unit", "")

        conclusion = payload.get("conclusion")
        confidence = payload.get("confidence", 0.0)

        if unit == "°":
            value_field = {"Angle": value}
        elif unit == "%":
            value_field = {"Ratio": value}
        else:
            value_field = {"Angle": value}

        # 调试：打印 conclusion 的值和类型
        logger.debug(
            "测量项 %s: conclusion=%s (type=%s), value=%s",
            name, conclusion, type(conclusion).__name__ if conclusion is not None else "None", value
        )
        
        level = _get_measurement_level(name, conclusion, value)
        
        # 确保 level 是 Python 原生 int 类型（防止 numpy 类型）
        if hasattr(level, 'item'):  # numpy 标量类型
            level = int(level.item())
        else:
            level = int(level)
        
        # 调试：打印最终 level
        logger.debug("测量项 %s: 最终 Level=%d (type=%s)", name, level, type(level).__name__)
        
        entry = {
            "Label": name,
            **value_field,
            "Level": level,  # 确保是 Python 原生 int
            "Confidence": round(confidence, 4),
        }
        section.append(entry)

    return section

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
                    return int(level)  # 确保返回 Python 原生 int
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
                return int(1)  # 骨性II类，确保返回 Python 原生 int
            if num_value < ANB_SKELETAL_III_THRESHOLD:
                return int(2)  # 骨性III类
            return int(0)  # 骨性I类
        
        # 下颌平面角(FH_MP_Angle)：均角=0, 高角=1, 低角=2
        if name == "FH_MP_Angle":
            if num_value > FH_MP_HIGH_ANGLE_THRESHOLD:
                return int(1)  # 高角
            if num_value < FH_MP_LOW_ANGLE_THRESHOLD:
                return int(2)  # 低角
            return int(0)  # 均角
        
        # 面部高度比例(SGo_NMe_Ratio)：平均生长型=0, 水平生长型=1, 垂直生长型=2
        if name.startswith("SGo_NMe_Ratio"):
            if num_value > SGO_NME_HORIZONTAL_THRESHOLD:
                return int(1)  # 水平生长型
            if num_value < SGO_NME_VERTICAL_THRESHOLD:
                return int(2)  # 垂直生长型
            return int(0)  # 平均生长型
    except (ValueError, TypeError):
        pass
    
    # 默认返回 0（确保返回 Python 原生 int）
    return int(0)

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
