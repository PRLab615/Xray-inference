# -*- coding: utf-8 -*-
"""侧位片重算模块：基于修改后的关键点坐标重新计算所有测量值。"""

from __future__ import annotations

import logging
from statistics import mean
from typing import Any, Dict, List

import numpy as np

from .ceph_report import (
    KEYPOINT_MAP,
    KEYPOINT_MAP_11,
    calculate_measurements,
    calculate_airway_measurements,
    calculate_adenoid_ratio,
)
from .ceph_report_json import (
    LABEL_FULL_NAMES,
    MEASUREMENT_ORDER,
    _build_measurement_entry,
    _visibility_grade,
)

logger = logging.getLogger(__name__)

# 反向映射：完整标签名 -> P-key（用于从前端 JSON 恢复关键点坐标）
FULL_NAME_TO_PKEY: Dict[str, str] = {}
for pkey, short_label in KEYPOINT_MAP.items():
    full_name = LABEL_FULL_NAMES.get(short_label, short_label)
    FULL_NAME_TO_PKEY[full_name] = pkey
    # 同时支持短标签名（兼容性）
    FULL_NAME_TO_PKEY[short_label] = pkey

# 11 点反向映射：完整标签名 -> key（用于从前端 JSON 恢复 11 点坐标）
FULL_NAME_TO_KEY_11: Dict[str, str] = {}
for key, short_label in KEYPOINT_MAP_11.items():
    full_name = LABEL_FULL_NAMES.get(short_label, short_label)
    FULL_NAME_TO_KEY_11[full_name] = key
    # 同时支持短标签名（兼容性）
    FULL_NAME_TO_KEY_11[short_label] = key


def recalculate_ceph_report(
    input_data: Dict[str, Any],
    gender: str,
    dental_age_stage: str,
    pixel_spacing: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    基于客户端修改后的数据重新计算侧位片报告。
    
    因果关系：
        "因"字段（从 input_data 提取）：
        - ImageSpacing.X/Y → spacing
        - LandmarkPositions.Landmarks[*] → 关键点坐标
        - Cervical_Vertebral_Maturity_Stage → 透传（模型直推结果）
        
        "果"字段（重新计算）：
        - VisibilityMetrics
        - MissingPointHandling
        - StatisticalFields
        - LandmarkPositions 统计字段
        - 除 Cervical_Vertebral_Maturity_Stage 外的所有测量值
    
    Args:
        input_data: 客户端传入的完整推理结果 JSON
        gender: 性别 ("Male" / "Female")
        dental_age_stage: 牙期 ("Permanent" / "Mixed")
        pixel_spacing: 由 API 层解析后的比例尺信息（可选）
            格式: {"scale_x": float, "scale_y": float, "source": str}
            如果为 None，则从 input_data.ImageSpacing 获取
    
    Returns:
        重算后的完整报告 JSON
    """
    # ========== 1. 提取"因"字段 ==========
    
    # 1.1 提取 spacing：优先使用传入的 pixel_spacing，否则从 input_data 获取
    if pixel_spacing and pixel_spacing.get("scale_x"):
        spacing_x = pixel_spacing["scale_x"]
        spacing_y = pixel_spacing.get("scale_y", spacing_x)
        spacing_source = pixel_spacing.get("source", "unknown")
        logger.info(
            f"[Ceph Recalculate] Using pixel_spacing from API: "
            f"X={spacing_x:.4f}, Y={spacing_y:.4f} mm/pixel, source={spacing_source}"
        )
    else:
        # 从 input_data 获取（兼容直接调用的场景）
        image_spacing = input_data.get("ImageSpacing")
        if not image_spacing or not image_spacing.get("X"):
            raise ValueError(
                "[PixelSpacing] Neither pixel_spacing parameter nor input_data.ImageSpacing is valid. "
                "Please provide pixel_spacing or ensure input_data contains valid ImageSpacing."
            )
        spacing_x = image_spacing.get("X")
        spacing_y = image_spacing.get("Y", spacing_x)
        logger.info(
            f"[Ceph Recalculate] Using ImageSpacing from input_data: "
            f"X={spacing_x:.4f}, Y={spacing_y:.4f} mm/pixel"
        )
    
    # 使用 X 方向的 spacing（假设等比例）
    spacing = float(spacing_x)
    
    # 1.2 提取 25 点关键点坐标（以及可能已合并的 11 点）
    landmark_positions = input_data.get("LandmarkPositions", {})
    input_landmarks = landmark_positions.get("Landmarks", [])

    # 1.3 提取 11 点关键点坐标（兼容两种输入：独立字段或已合并进 LandmarkPositions）
    input_landmarks_11: List[Dict[str, Any]] = []
    airway_landmark_positions = input_data.get("AirwayLandmarkPositions")
    if isinstance(airway_landmark_positions, dict) and airway_landmark_positions.get("Landmarks"):
        # 旧格式：单独字段
        input_landmarks_11 = airway_landmark_positions.get("Landmarks", [])
    else:
        # 新格式：已合并到 LandmarkPositions 中，从中筛选 11 点标签
        if isinstance(input_landmarks, list) and input_landmarks:
            # FULL_NAME_TO_KEY_11 在模块顶部已构建
            eleven_full_names = set(FULL_NAME_TO_KEY_11.keys())
            input_landmarks_11 = [lm for lm in input_landmarks if lm.get("Label") in eleven_full_names]
    has_landmarks_11 = len(input_landmarks_11) > 0
    
    # 1.4 提取颈椎成熟度（透传）
    input_measurements = input_data.get("CephalometricMeasurements", {})
    input_all_measurements = input_measurements.get("AllMeasurements", [])
    cervical_entry = _extract_cervical_entry(input_all_measurements)
    
    # ========== 2. 转换关键点格式 ==========
    # 2.1 转换 25 点
    landmarks_dict, landmark_entries, confidence_values = _convert_landmarks(input_landmarks)
    
    # 2.2 转换 11 点（如果存在）
    landmarks_11_dict = {}
    landmark_11_entries = []
    confidence_11_values = []
    if has_landmarks_11:
        landmarks_11_dict, landmark_11_entries, confidence_11_values = _convert_landmarks_11(input_landmarks_11)
    
    # ========== 3. 计算统计信息 ==========
    # 3.1 25 点统计
    total_landmarks = len(KEYPOINT_MAP)
    detected_count = sum(1 for e in landmark_entries if e["Status"] == "Detected")
    missing_count = total_landmarks - detected_count
    missing_labels = [e["Label"] for e in landmark_entries if e["Status"] == "Missing"]
    average_confidence = round(mean(confidence_values), 2) if confidence_values else 0.0
    
    # 3.2 11 点统计
    total_landmarks_11 = len(KEYPOINT_MAP_11) if has_landmarks_11 else 0
    detected_count_11 = sum(1 for e in landmark_11_entries if e["Status"] == "Detected") if has_landmarks_11 else 0
    missing_count_11 = total_landmarks_11 - detected_count_11
    missing_labels_11 = [e["Label"] for e in landmark_11_entries if e["Status"] == "Missing"] if has_landmarks_11 else []
    average_confidence_11 = round(mean(confidence_11_values), 2) if confidence_11_values else 0.0
    
    # ========== 4. 重新计算测量值 ==========
    sex = gender.lower()  # calculate_measurements 期望小写
    dentition = dental_age_stage.lower()
    
    # 4.1 计算 25 点相关测量值
    measurements = calculate_measurements(
        landmarks=landmarks_dict,
        sex=sex,
        dentition=dentition,
        spacing=spacing,
    )
    
    # 4.2 计算气道和腺体测量值（如果有 11 点）
    if has_landmarks_11:
        airway_result = calculate_airway_measurements(
            landmarks_25=landmarks_dict,
            landmarks_11=landmarks_11_dict,
            spacing=spacing,
        )
        adenoid_result = calculate_adenoid_ratio(
            landmarks_25=landmarks_dict,
            landmarks_11=landmarks_11_dict,
            spacing=spacing,
        )
        # 合并到 measurements
        measurements["Airway_Gap"] = airway_result
        measurements["Adenoid_Index"] = adenoid_result
        logger.info(
            "[Ceph Recalculate] 气道和腺体重算完成: 气道=%s, A/N=%.2f",
            "正常" if airway_result.get("conclusion", False) else "不足",
            adenoid_result.get("value", 0.0),
        )
    
    # ========== 5. 构建输出 JSON ==========
    
    # 5.1 VisibilityMetrics（重算）
    visibility_grade = _visibility_grade(detected_count, total_landmarks)
    
    # 5.2 构建测量值列表（保留 Cervical_Vertebral_Maturity_Stage 原值）
    measurement_section = _build_measurement_section_with_cervical(
        measurements=measurements,
        cervical_entry=cervical_entry,
    )
    
    # 5.3 计算总的统计信息（25点 + 11点）并合并列表
    total_all_landmarks = total_landmarks + total_landmarks_11
    detected_all_count = detected_count + detected_count_11
    all_missing_labels = missing_labels + missing_labels_11
    combined_entries = landmark_entries + (landmark_11_entries if has_landmarks_11 else [])

    # 5.4 组装完整输出（关键变更：仅保留合并后的 LandmarkPositions，不再输出 AirwayLandmarkPositions）
    output_data = {
        "ImageSpacing": {
            "X": spacing_x,
            "Y": spacing_y,
            "Unit": "mm/pixel",
        },
        "VisibilityMetrics": {
            "Grade": visibility_grade,
            "MissingLandmarks": all_missing_labels,
        },
        "MissingPointHandling": {
            "Method": "插值估算",
            "ConfidenceThreshold": 0.7,
            "InterpolationAllowed": False,
        },
        "StatisticalFields": {
            "ProcessedLandmarks": detected_all_count,
            "MissingLandmarks": total_all_landmarks - detected_all_count,
            "AverageConfidence": average_confidence,
            "QualityScore": average_confidence,
        },
        "PatientInformation": {
            "Gender": gender,
            "DentalAgeStage": {
                "CurrentStage": dental_age_stage,
            },
        },
        "LandmarkPositions": {
            "TotalLandmarks": total_all_landmarks,
            "DetectedLandmarks": detected_all_count,
            "MissingLandmarks": total_all_landmarks - detected_all_count,
            "MissingLabels": all_missing_labels,
            "Landmarks": combined_entries,
        },
        "CephalometricMeasurements": {
            "AllMeasurements": measurement_section,
        },
    }

    logger.info(
        "[Ceph Recalculate] Generated report (merged): %d/%d landmarks (25+11), %d measurements",
        detected_all_count,
        total_all_landmarks,
        len(measurement_section),
    )

    return output_data


def _convert_landmarks(
    input_landmarks: List[Dict[str, Any]]
) -> tuple[Dict[str, np.ndarray], List[Dict[str, Any]], List[float]]:
    """
    将前端 JSON 格式的关键点转换为 calculate_measurements 期望的格式。
    
    Args:
        input_landmarks: 前端传入的关键点列表
            [{"Label": "Sella", "X": 100, "Y": 200, "Confidence": 0.95, "Status": "Detected"}, ...]
    
    Returns:
        tuple:
            - landmarks_dict: {P1: np.array([x, y]), ...} 用于计算
            - landmark_entries: 保持原格式的关键点列表（用于输出）
            - confidence_values: 已检测关键点的置信度列表（用于统计）
    """
    landmarks_dict: Dict[str, np.ndarray] = {}
    landmark_entries: List[Dict[str, Any]] = []
    confidence_values: List[float] = []
    
    # 创建输入 landmarks 的索引（按 Label 查找）
    input_by_label: Dict[str, Dict[str, Any]] = {}
    for lm in input_landmarks:
        label = lm.get("Label", "")
        input_by_label[label] = lm
    
    # 按 KEYPOINT_MAP 顺序遍历，确保输出顺序一致
    for pkey, short_label in KEYPOINT_MAP.items():
        full_label = LABEL_FULL_NAMES.get(short_label, short_label)
        
        # 尝试从输入中找到对应的关键点（支持完整名或短名）
        lm = input_by_label.get(full_label) or input_by_label.get(short_label)
        
        if lm:
            x = lm.get("X")
            y = lm.get("Y")
            confidence = lm.get("Confidence", 0.0)
            status = lm.get("Status", "Missing")
            
            # 判断是否为有效点
            if x is not None and y is not None and status == "Detected":
                landmarks_dict[pkey] = np.array([float(x), float(y)])
                confidence_values.append(float(confidence))
            else:
                # 缺失点：设置为 NaN
                landmarks_dict[pkey] = np.array([np.nan, np.nan])
            
            # 保留原始条目（用于输出）
            landmark_entries.append({
                "Label": full_label,
                "X": int(x) if x is not None else None,
                "Y": int(y) if y is not None else None,
                "Confidence": round(float(confidence), 2) if status == "Detected" else 0.00,
                "Status": status,
            })
        else:
            # 输入中没有该关键点，标记为缺失
            landmarks_dict[pkey] = np.array([np.nan, np.nan])
            landmark_entries.append({
                "Label": full_label,
                "X": None,
                "Y": None,
                "Confidence": 0.00,
                "Status": "Missing",
            })
    
    return landmarks_dict, landmark_entries, confidence_values


def _convert_landmarks_11(
    input_landmarks: List[Dict[str, Any]]
) -> tuple[Dict[str, np.ndarray], List[Dict[str, Any]], List[float]]:
    """
    将前端 JSON 格式的 11 点（气道/腺体）转换为 calculate_airway_measurements 期望的格式。
    
    Args:
        input_landmarks: 前端传入的 11 点关键点列表
            [{"Label": "Uvula tip", "X": 100, "Y": 200, "Confidence": 0.95, "Status": "Detected"}, ...]
    
    Returns:
        tuple:
            - landmarks_dict: {"U": np.array([x, y]), ...} 用于计算
            - landmark_entries: 保持原格式的关键点列表（用于输出）
            - confidence_values: 已检测关键点的置信度列表（用于统计）
    """
    landmarks_dict: Dict[str, np.ndarray] = {}
    landmark_entries: List[Dict[str, Any]] = []
    confidence_values: List[float] = []
    
    # 创建输入 landmarks 的索引（按 Label 查找）
    input_by_label: Dict[str, Dict[str, Any]] = {}
    for lm in input_landmarks:
        label = lm.get("Label", "")
        input_by_label[label] = lm
    
    # 按 KEYPOINT_MAP_11 顺序遍历，确保输出顺序一致
    for key, short_label in KEYPOINT_MAP_11.items():
        full_label = LABEL_FULL_NAMES.get(short_label, short_label)
        
        # 尝试从输入中找到对应的关键点（支持完整名或短名）
        lm = input_by_label.get(full_label) or input_by_label.get(short_label)
        
        if lm:
            x = lm.get("X")
            y = lm.get("Y")
            confidence = lm.get("Confidence", 0.0)
            status = lm.get("Status", "Missing")
            
            # 判断是否为有效点
            if x is not None and y is not None and status == "Detected":
                landmarks_dict[key] = np.array([float(x), float(y)])
                confidence_values.append(float(confidence))
            else:
                # 缺失点：设置为 NaN
                landmarks_dict[key] = np.array([np.nan, np.nan])
            
            # 保留原始条目（用于输出）
            landmark_entries.append({
                "Label": full_label,
                "X": int(x) if x is not None else None,
                "Y": int(y) if y is not None else None,
                "Confidence": round(float(confidence), 2) if status == "Detected" else 0.00,
                "Status": status,
            })
        else:
            # 输入中没有该关键点，标记为缺失
            landmarks_dict[key] = np.array([np.nan, np.nan])
            landmark_entries.append({
                "Label": full_label,
                "X": None,
                "Y": None,
                "Confidence": 0.00,
                "Status": "Missing",
            })
    
    return landmarks_dict, landmark_entries, confidence_values


def _extract_cervical_entry(
    input_measurements: List[Dict[str, Any]]
) -> Dict[str, Any] | None:
    """
    从输入测量值列表中提取 Cervical_Vertebral_Maturity_Stage 条目。
    
    Args:
        input_measurements: 输入的测量值列表
    
    Returns:
        颈椎成熟度条目，若不存在则返回 None
    """
    for entry in input_measurements:
        if entry.get("Label") == "Cervical_Vertebral_Maturity_Stage":
            return entry
    return None


def _build_measurement_section_with_cervical(
    measurements: Dict[str, Dict[str, Any]],
    cervical_entry: Dict[str, Any] | None,
) -> List[Dict[str, Any]]:
    """
    按照 MEASUREMENT_ORDER 顺序构建测量值列表。
    
    对于 Cervical_Vertebral_Maturity_Stage，透传原值；
    其他测量项使用 calculate_measurements 的计算结果。
    
    Args:
        measurements: calculate_measurements 返回的测量结果
        cervical_entry: 从输入中提取的颈椎成熟度条目（透传）
    
    Returns:
        按顺序排列的测量值列表
    """
    section: List[Dict[str, Any]] = []
    
    for name in MEASUREMENT_ORDER:
        if name == "Cervical_Vertebral_Maturity_Stage":
            # 透传颈椎成熟度（模型直推结果）
            if cervical_entry:
                section.append(cervical_entry)
            else:
                # 没有颈椎数据时，构建一个空条目
                section.append({
                    "Label": name,
                    "Coordinates": [],
                    "SerializedMask": "",
                    "Level": -1,  # 未检测
                    "Confidence": 0.0,
                })
        else:
            # 使用重算结果
            payload = measurements.get(name, {})
            entry = _build_measurement_entry(name, payload)
            section.append(entry)
    
    return section

