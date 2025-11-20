# -*- coding: utf-8 -*-
"""侧位片报告生成工具：将推理结果格式化为规范 JSON。"""

from __future__ import annotations

import logging
from statistics import mean
from typing import Any, Dict, List

import numpy as np

from .ceph_report import KEYPOINT_MAP

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
            "Method": "SkipMeasurement",
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
                #"Key": key,
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


        level = 0 if conclusion is None or "正常" in str(conclusion) else 1

        entry = {
            "Label": name,
            **value_field,
            "Level": level,
            "Confidence": round(confidence, 4),
        }
        section.append(entry)

    return section

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
