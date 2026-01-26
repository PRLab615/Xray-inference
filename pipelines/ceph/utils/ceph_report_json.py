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
    KEYPOINT_MAP_11,
    KEYPOINT_MAP_34,
    ANB_SKELETAL_II_THRESHOLD,
    ANB_SKELETAL_III_THRESHOLD,
    FH_MP_HIGH_ANGLE_THRESHOLD,
    FH_MP_LOW_ANGLE_THRESHOLD,
    SGO_NME_HORIZONTAL_THRESHOLD,
    SGO_NME_VERTICAL_THRESHOLD,
    DEFAULT_SPACING_MM_PER_PIXEL,
)
from .ceph_visualization import build_visualization_map

logger = logging.getLogger(__name__)

# 关键点简称到完整名称的映射（用于输出）
LABEL_FULL_NAMES = {
    # 25点名称
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
    # 11点名称（气道/腺体）
    "U": "Uvula tip",  # 悬雍垂尖
    "V": "Vallecula",  # 会咽谷点
    "UPW": "Upper Pharyngeal Wall",  # 上咽壁点
    "SPP": "Soft Palate Point",  # 软腭前点
    "SPPW": "Soft Palate Pharyngeal Wall",  # 软腭后咽壁点
    "MPW": "Middle Pharyngeal Wall",  # 中咽壁点
    "LPW": "Lower Pharyngeal Wall",  # 下咽壁点
    "TB": "Tongue Base",  # 舌根点
    "TPPW": "Tongue Posterior Pharyngeal Wall",  # 舌咽部后气道点
    "AD": "Adenoid",  # 腺样体最凸点
    "D'": "D'",  # 翼板与颅底交点
}

# 在 report.py 文件顶部（import 之后，MEASUREMENT_ORDER 之前）添加

MEASUREMENT_DISPLAY_NAMES = {
    "Reference_Planes": "参考平面",
    "ANB_Angle": "ANB °",
    "PtmANS_Length": "Ptm-ANS mm",
    "GoPo_Length": "Go-Po mm",
    "PoNB_Length": "Po-NB mm",
    "Jaw_Development_Coordination": "上下颌骨发育协调",
    "SGo_NMe_Ratio": "S-Go/N-Me (%)",
    "FH_MP_Angle": "FH-MP °",
    "IMPA_Angle": "IMPA(L1-MP)°",
    "Airway_Gap": "气道间隙",
    "Adenoid_Index": "腺样体指数 (A/N)",
    "SNA_Angle": "SNA °",
    "Upper_Jaw_Position": "Ptm-S mm",
    "SNB_Angle": "SNB °",
    "Pcd_Lower_Position": "Pcd-S mm",
    "Distance_Witsmm": "Wits值mm",
    "U1_SN_Angle": "U1-SN °",
    "U1_NA_Angle": "U1-NA角°",
    "U1_NA_Incisor_Length": "U1-NA距mm",
    "FMIA_Angle": "FMIA(L1-FH)°",
    "L1_NB_Angle": "L1-NB角 °",
    "L1_NB_Distance": "L1-NB距 mm",
    "U1_L1_Inter_Incisor_Angle": "U1-LI °",
    "Y_Axis_Angle": "Y轴角 °",
    "Mandibular_Growth_Angle": "NBa-PTGn °",
    "SN_MP_Angle": "SN-MP °",
    "U1_PP_Upper_Anterior_Alveolar_Height": "U1-PP mm",
    "L1_MP_Lower_Anterior_Alveolar_Height": "L1-MP mm",
    "U6_PP_Upper_Posterior_Alveolar_Height": "U6-PP mm",
    "L6_MP_Lower_Posterior_Alveolar_Height": "L6-MP mm",
    "Mandibular_Growth_Type_Angle": "S+Ar+Go（Bjork sum）",
    "S_N_Anterior_Cranial_Base_Length": "S-N mm",
    "Go_Me_Length": "Go-Me mm",
    "Cervical_Vertebral_Maturity_Stage": "CVSM边缘形状",
    "Profile_Contour": "侧貌轮廓 (P1-P34)",
}

MEASUREMENT_ORDER = [
    "Reference_Planes",
    "ANB_Angle",
    "PtmANS_Length",
    "GoPo_Length",
    "PoNB_Length",
    "Jaw_Development_Coordination",
    "SGo_NMe_Ratio",
    "FH_MP_Angle",
    "IMPA_Angle",
    "Airway_Gap",  # 可选
    "Adenoid_Index",  # 可选
    "Profile_Contour", # 可选 (34点)
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
    "Y_Axis_Angle",  # ㉗ Y轴角（原 Y_SGo_NMe_Ratio-2，已修正命名）
    "Mandibular_Growth_Angle",
    "SN_MP_Angle",  # ㉚ SN-MP角（原 SN_FH_Angle-1，已修正命名）
    "U1_PP_Upper_Anterior_Alveolar_Height",
    "L1_MP_Lower_Anterior_Alveolar_Height",
    "U6_PP_Upper_Posterior_Alveolar_Height",
    "L6_MP_Lower_Posterior_Alveolar_Height",
    "Mandibular_Growth_Type_Angle",  # Björk sum
    "S_N_Anterior_Cranial_Base_Length",
    "Go_Me_Length",
    "Cervical_Vertebral_Maturity_Stage",
]

# 特殊测量项类型定义
MULTISELECT_MEASUREMENTS = {"Jaw_Development_Coordination"}
AIRWAY_MEASUREMENTS = {"Airway_Gap"}
ADENOID_MEASUREMENTS = {"Adenoid_Index"}
BOOLEAN_LEVEL_MEASUREMENTS = {"Airway_Gap", "Adenoid_Index"}
CERVICAL_VERTEBRAL_MEASUREMENTS = {"Cervical_Vertebral_Maturity_Stage"}

# 测量项分类：用于将测量项分组到不同的类别
CEPHALOMETRIC_MEASUREMENT_NAMES = {
    "Reference_Planes",
    "ANB_Angle",
    "PtmANS_Length",
    "GoPo_Length",
    "PoNB_Length",
    "Jaw_Development_Coordination",
    "SGo_NMe_Ratio",
    "FH_MP_Angle",
    "IMPA_Angle",
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
    "Y_Axis_Angle",
    "Mandibular_Growth_Angle",
    "SN_MP_Angle",
    "U1_PP_Upper_Anterior_Alveolar_Height",
    "L1_MP_Lower_Anterior_Alveolar_Height",
    "U6_PP_Upper_Posterior_Alveolar_Height",
    "L6_MP_Lower_Posterior_Alveolar_Height",
    "Mandibular_Growth_Type_Angle",
    "S_N_Anterior_Cranial_Base_Length",
    "Go_Me_Length",
}

BONE_AGE_MEASUREMENT_NAMES = {
    "Cervical_Vertebral_Maturity_Stage",
}

AIRWAY_MEASUREMENT_NAMES = {
    "Airway_Gap",
    "Adenoid_Index",
}

PROFILE_MEASUREMENT_NAMES = {
    "Profile_Contour",
}

# 未检测标识：Level=-1 表示该测量项未被模型检测到
UNDETECTED_LEVEL = -1


def generate_standard_output(
        inference_results: Dict[str, Any],
        patient_info: Dict[str, str],
        auto_ruler_result: Optional[Dict[str, Any]] = None,
        visualization_enabled: bool = True,
) -> Dict[str, Any]:
    """
    将推理结果映射为符合《接口定义.md》的 data 字段。

    Args:
        inference_results: 推理结果，包含 landmarks, landmarks_11, measurements, spacing
        patient_info: 患者信息

    Returns:
        符合规范的 data 字段

    注意：
        spacing 已由 point_model.run() 处理并放入 inference_results["spacing"]
        优先级为：DICOM/请求参数 > patient_info["PixelSpacing"] > 默认值
    """
    landmarks_block = inference_results.get("landmarks", {})
    landmarks_11_block = inference_results.get("landmarks_11", {})  # 11点结果
    landmarks_34_block = inference_results.get("landmarks_34", {})  # 34点结果
    measurements = inference_results.get("measurements", {})
    
    # 如果存在34点结果，注入 Profile_Contour 测量项以触发可视化
    if landmarks_34_block:
        if "Profile_Contour" not in measurements:
             measurements["Profile_Contour"] = {"status": "ok", "value": 0}

    # 从推理结果获取实际使用的 spacing，如果没有则使用默认值
    spacing = inference_results.get("spacing", DEFAULT_SPACING_MM_PER_PIXEL)

    # 构建 25 点的 landmark section（头影组）
    cephalometric_landmarks = _build_landmark_section(landmarks_block)

    # 构建 11 点的 landmark section（气道组）
    airway_landmarks = None
    if landmarks_11_block:
        airway_landmarks = _build_landmark_11_section(landmarks_11_block)

    # 构建 34 点的 landmark section（侧貌轮廓组）
    profile_landmarks = None
    if landmarks_34_block:
        profile_landmarks = _build_landmark_34_section(landmarks_34_block)

    # 构建可视化映射
    viz_map = (
        build_visualization_map(measurements, landmarks_block, landmarks_11_block, landmarks_34_block)
        if visualization_enabled
        else None
    )

    # 将测量项按类别拆分
    cephalometric_measurements, bone_age_measurements, airway_measurements, profile_measurements = (
        _split_measurements_by_category(measurements, viz_map)
    )

    # 计算总的 landmark 统计（25点 + 11点 + 34点）
    total_landmarks = cephalometric_landmarks["TotalLandmarks"]
    detected_landmarks = cephalometric_landmarks["DetectedLandmarks"]
    missing_labels = cephalometric_landmarks["MissingLabels"].copy()

    if airway_landmarks:
        total_landmarks += airway_landmarks["TotalLandmarks"]
        detected_landmarks += airway_landmarks["DetectedLandmarks"]
        missing_labels.extend(airway_landmarks["MissingLabels"])

    if profile_landmarks:
        total_landmarks += profile_landmarks["TotalLandmarks"]
        detected_landmarks += profile_landmarks["DetectedLandmarks"]
        missing_labels.extend(profile_landmarks["MissingLabels"])

    # 计算合并后的可视性等级与统计
    visibility_grade = _visibility_grade(detected_landmarks, total_landmarks)

    # 计算平均置信度（合并所有）
    all_confidences = []
    for lm in cephalometric_landmarks["Landmarks"]:
        if lm["Status"] == "Detected":
            all_confidences.append(lm["Confidence"])
    if airway_landmarks:
        for lm in airway_landmarks["Landmarks"]:
            if lm["Status"] == "Detected":
                all_confidences.append(lm["Confidence"])
    if profile_landmarks:
        for lm in profile_landmarks["Landmarks"]:
            if lm["Status"] == "Detected":
                all_confidences.append(lm["Confidence"])

    average_confidence = round(mean(all_confidences), 2) if all_confidences else 0.0

    # 构建 LandmarkPositions：按类别拆分
    landmark_positions = {
        "CephalometricLandmarks": cephalometric_landmarks["Landmarks"],
        "AirwayLandmarks": airway_landmarks["Landmarks"] if airway_landmarks else [],
        "ProfileLandmarks": profile_landmarks["Landmarks"] if profile_landmarks else [],
        # BoneAgeLandmarks 字段已移除，因为骨龄通过测量项（CVM）体现，无独立点位
    }

    data_dict = {
        "ImageSpacing": {
            "X": spacing,
            "Y": spacing,
            "Unit": "mm/pixel",
        },
        "VisibilityMetrics": {
            "Grade": visibility_grade,
            "MissingLandmarks": missing_labels,
        },
        "MissingPointHandling": {
            "Method": "插值估算",
            "ConfidenceThreshold": 0.7,
            "InterpolationAllowed": False,
        },
        "StatisticalFields": {
            "TotalLandmarks": total_landmarks,
            "ProcessedLandmarks": detected_landmarks,
            "MissingLandmarks": total_landmarks - detected_landmarks,
            "AverageConfidence": round(average_confidence, 2),
            "QualityScore": round(average_confidence, 2),
        },
        "PatientInformation": {
            "Gender": patient_info.get("gender", "Male"),
            "DentalAgeStage": {
                "CurrentStage": patient_info.get("DentalAgeStage", "Permanent"),
            },
        },
        # 关键变更：LandmarkPositions 按类别拆分为三组
        "LandmarkPositions": landmark_positions,
        # 关键变更：Measurements 按类别拆分为三组
        "Measurements": {
            "CephalometricMeasurements": cephalometric_measurements,
            "BoneAgeMeasurements": bone_age_measurements,
            "AirwayMeasurements": airway_measurements,
            "ProfileMeasurements": profile_measurements,
        },
        "auto_ruler": auto_ruler_result,
    }

    logger.info(
        "Generated cephalometric JSON (split by category): "
        "%s ceph landmarks, %s airway landmarks | "
        "%s ceph measurements, %s bone-age measurements, %s airway measurements, %s profile measurements",
        len(cephalometric_landmarks["Landmarks"]),
        len(airway_landmarks["Landmarks"]) if airway_landmarks else 0,
        len(cephalometric_measurements),
        len(bone_age_measurements),
        len(airway_measurements),
        len(profile_measurements),
    )
    return data_dict


def _build_landmark_11_section(landmarks_block: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建 11 点（气道/腺体）的 landmark section
    """
    coordinates: Dict[str, Any] = landmarks_block.get("coordinates", {})
    confidences: Dict[str, float] = landmarks_block.get("confidences", {})

    entries: List[Dict[str, Any]] = []
    detected = 0
    missing_labels: List[str] = []
    confidence_values: List[float] = []

    for key, short_label in KEYPOINT_MAP_11.items():
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

    total = len(KEYPOINT_MAP_11)
    average_confidence = round(mean(confidence_values), 2) if confidence_values else 0.0

    return {
        "TotalLandmarks": total,
        "DetectedLandmarks": detected,
        "MissingLandmarks": total - detected,
        "Landmarks": entries,
        "MissingLabels": missing_labels,
        "AverageConfidence": average_confidence,
    }


def _build_landmark_34_section(landmarks_block: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建 34 点（侧貌轮廓）的 landmark section
    """
    coordinates: Dict[str, Any] = landmarks_block.get("coordinates", {})
    confidences: Dict[str, float] = landmarks_block.get("confidences", {})

    entries: List[Dict[str, Any]] = []
    detected = 0
    missing_labels: List[str] = []
    confidence_values: List[float] = []

    for key, short_label in KEYPOINT_MAP_34.items():
        # 使用完整标签名 (如果 LABEL_FULL_NAMES 中没有，则使用 short_label)
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

        formatted_confidence = round(confidence, 2) if status == "Detected" else 0.00

        entries.append(
            {
                "Label": full_label,
                "X": int(x_value) if x_value is not None else None,
                "Y": int(y_value) if y_value is not None else None,
                "Status": status,
                "Confidence": formatted_confidence,
            }
        )

    return {
        "TotalLandmarks": len(KEYPOINT_MAP_34),
        "DetectedLandmarks": detected,
        "MissingLabels": missing_labels,
        "Landmarks": entries,
    }


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


def _split_measurements_by_category(
        measurements: Dict[str, Dict[str, Any]],
        viz_map: Dict[str, Any] | None = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    将测量项按类别拆分为四组：头影、骨龄、气道、侧貌。

    Returns:
        (cephalometric_measurements, bone_age_measurements, airway_measurements, profile_measurements)
        每组都是测量项字典的列表，保持原有字段结构
    """
    cephalometric_list: List[Dict[str, Any]] = []
    bone_age_list: List[Dict[str, Any]] = []
    airway_list: List[Dict[str, Any]] = []
    profile_list: List[Dict[str, Any]] = []

    # 按照 MEASUREMENT_ORDER 顺序处理，确保顺序一致
    for name in MEASUREMENT_ORDER:
        payload = measurements.get(name, {})
        entry = _build_measurement_entry(name, payload, viz_map)

        # 根据测量项名称分类
        if name in BONE_AGE_MEASUREMENT_NAMES:
            bone_age_list.append(entry)
        elif name in AIRWAY_MEASUREMENT_NAMES:
            airway_list.append(entry)
        elif name in PROFILE_MEASUREMENT_NAMES:
            profile_list.append(entry)
        elif name in CEPHALOMETRIC_MEASUREMENT_NAMES:
            cephalometric_list.append(entry)
        else:
            # 未分类的测量项默认归入头影组
            logger.warning(f"测量项 {name} 未在分类列表中，默认归入头影组")
            cephalometric_list.append(entry)

    return cephalometric_list, bone_age_list, airway_list, profile_list


def _build_measurement_section_in_order(
        measurements: Dict[str, Dict[str, Any]],
        viz_map: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """
    关键修改：严格按照 MEASUREMENT_ORDER 顺序输出所有测量项
    缺失的项目也会占位（返回空值但保留Label），保证序号不乱

    注意：此函数已被 _split_measurements_by_category 替代，保留用于向后兼容
    """
    section: List[Dict[str, Any]] = []

    for name in MEASUREMENT_ORDER:
        payload = measurements.get(name, {})
        entry = _build_measurement_entry(name, payload, viz_map)
        section.append(entry)

    return section


def _build_measurement_section(
        measurements: Dict[str, Dict[str, Any]],
        viz_map: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    section: List[Dict[str, Any]] = []

    for name, payload in measurements.items():
        entry = _build_measurement_entry(name, payload, viz_map)
        section.append(entry)

    return section


def _build_measurement_entry(
        name: str,
        payload: Dict[str, Any],
        viz_map: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    根据测量项类型构建对应的输出格式。

    支持的类型：
    - 角度测量：{"Label": "...", "Angle": ..., "Level": int, "Confidence": ...}
    - 长度测量：{"Label": "...", "Length_mm": ..., "Level": int, "Confidence": ...}
    - 比率测量：{"Label": "...", "Ratio": ..., "Level": int, "Confidence": ...}
    - 多选类型：{"Label": "...", "Type": "MultiSelect", "Level": [int], "Confidence": ...}
    - 气道测量：{"Label": "...", "PNS-UPW": ..., ..., "Level": bool, "Confidence": ...}
    - 颈椎成熟度：{"Label": "...", "Coordinates": [...], "Level": int, "Confidence": ...}

    未检测标识：
    - 当 payload 为空或缺少 value 时，Level=-1 表示未检测到
    - 数值字段设为 null，Confidence=0.0
    """
    value = payload.get("value")
    unit = payload.get("unit", "")
    conclusion = payload.get("conclusion")
    confidence = payload.get("confidence", 0.0)
    status_ok = payload.get("status") == "ok"
    viz_payload = viz_map.get(name) if viz_map else None

    # 判断是否为未检测状态：payload 为空或 value 为 None
    is_undetected = not payload or value is None

    # 处理特殊类型
    if name in CERVICAL_VERTEBRAL_MEASUREMENTS:
        return _build_cervical_entry(name, payload)

    if name in AIRWAY_MEASUREMENTS:
        entry = _build_airway_entry(name, payload)
        entry["Visualization"] = _format_visualization(viz_payload) if status_ok else None
        return entry

    if name in ADENOID_MEASUREMENTS:
        entry = _build_adenoid_entry(name, payload)
        entry["Visualization"] = _format_visualization(viz_payload) if status_ok else None
        return entry

    if name in MULTISELECT_MEASUREMENTS:
        return _build_multiselect_entry(name, payload)

    # 标准测量项
    # entry: Dict[str, Any] = {"Label": name}
    display_name = MEASUREMENT_DISPLAY_NAMES.get(name, name)  # 未映射的保留英文
    entry: Dict[str, Any] = {"Label": display_name}

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
    entry["Visualization"] = _format_visualization(viz_payload) if status_ok else None

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
    cvms_mask = payload.get("CVMSMask", [])

    return {
        "Label": name,
        "Coordinates": coordinates if not is_undetected else [],
        "Level": int(level) if level is not None else UNDETECTED_LEVEL,
        "Confidence": round(float(confidence), 2),
        "CVMSMask": cvms_mask,
    }


def _build_airway_entry(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建气道测量项。

    格式：{"Label": "Airway_Gap", "PNS-UPW": ..., "SPP-SPPW": ...,
           "U-MPW": ..., "TB-TPPW": ..., "V-LPW": ..., "Level": bool, "Confidence": ...}

    未检测标识：当 payload 为空时，所有气道值为 null，Level=null（而非 true/false）
    """
    entry: Dict[str, Any] = {"Label": name}

    # 判断是否为未检测状态
    is_undetected = not payload

    # 提取各个气道距离值（注意：TB-TPPW 而非 TB-YPPW）
    airway_keys = ["PNS-UPW", "SPP-SPPW", "U-MPW", "TB-TPPW", "V-LPW"]
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


def _build_adenoid_entry(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建腺样体指数测量项。

    格式：{"Label": "Adenoid_Index", "Value": 0.5, "Level": bool, "Confidence": ...}

    未检测标识：当 payload 为空时，Value=null，Level=null
    """
    entry: Dict[str, Any] = {"Label": name}

    # 判断是否为未检测状态
    is_undetected = not payload or payload.get("value") is None

    # 提取 A/N 比值
    value = payload.get("value")
    entry["Value"] = _format_value(value)

    # 未检测时 Level 设为 null
    if is_undetected:
        entry["Level"] = None
    else:
        # 腺样体测量的 Level 为 bool
        # True=未见肿大(<0.7), False=肿大(>=0.7)
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


def _format_visualization(raw: Any) -> Union[Dict[str, Any], None]:
    if not isinstance(raw, dict):
        return None

    virtual_points_raw = raw.get("VirtualPoints")
    elements_raw = raw.get("Elements")
    polygon_raw = raw.get("Polygon")

    formatted_vp: Dict[str, List[float]] | None = None
    if isinstance(virtual_points_raw, dict):
        formatted_vp = {}
        for key, value in virtual_points_raw.items():
            arr = np.asarray(value, dtype=float)
            if arr.shape[0] < 2 or np.isnan(arr).any():
                continue
            formatted_vp[key] = [round(float(arr[0]), 2), round(float(arr[1]), 2)]
        if not formatted_vp:
            formatted_vp = None

    formatted_elements: List[Dict[str, Any]] | None = None
    if isinstance(elements_raw, list):
        formatted_elements = []
        for item in elements_raw:
            if not isinstance(item, dict):
                continue

            item_type = item.get("Type")
            if item_type == "Line":
                from_key = item.get("From")
                to_key = item.get("To")
                style = item.get("Style")
                role = item.get("Role")
                if None in (from_key, to_key, style, role):
                    continue
                formatted_elements.append(
                    {
                        "Type": "Line",
                        "From": from_key,
                        "To": to_key,
                        "Style": style,
                        "Role": role,
                    }
                )
                continue

            if item_type == "Angle":
                vertex = item.get("Vertex")
                point1 = item.get("Point1")
                point2 = item.get("Point2")
                role = item.get("Role")
                if None in (vertex, point1, point2, role):
                    continue
                formatted_elements.append(
                    {
                        "Type": "Angle",
                        "Vertex": vertex,
                        "Point1": point1,
                        "Point2": point2,
                        "Role": role,
                    }
                )
                continue
        if not formatted_elements:
            formatted_elements = None

    formatted_polygon: List[float] | None = None
    if isinstance(polygon_raw, (list, tuple)) and len(polygon_raw) >= 6:
        # 扁平浮点数组 [x1,y1,x2,y2,...]
        try:
            arr = np.asarray(polygon_raw, dtype=float)
            if arr.ndim == 1 and arr.size % 2 == 0 and not np.isnan(arr).any():
                formatted_polygon = [round(float(v), 2) for v in arr.tolist()]
        except Exception:
            formatted_polygon = None

    if formatted_vp is None and formatted_elements is None and formatted_polygon is None:
        return None

    out: Dict[str, Any] = {"VirtualPoints": formatted_vp, "Elements": formatted_elements}
    if formatted_polygon is not None:
        out["Polygon"] = formatted_polygon
    return out


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
                logger.warning(
                    f"测量项 {name}: 无法将 conclusion={conclusion} (type={type(conclusion).__name__}) 转换为 int: {e}，将使用 value 重新计算")

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
