# -*- coding: utf-8 -*-
"""侧位片重算模块：基于修改后的关键点坐标重新计算所有测量值。"""

from __future__ import annotations

import logging
from statistics import mean
from typing import Any, Dict, List, Optional

import numpy as np

from .ceph_report import (
    KEYPOINT_MAP,
    KEYPOINT_MAP_11,
    KEYPOINT_MAP_34,
    calculate_measurements,
    calculate_airway_measurements,
    calculate_adenoid_ratio,
)
from .ceph_report_json import (
    LABEL_FULL_NAMES,
    generate_standard_output,
)

logger = logging.getLogger(__name__)

# 反向映射：完整标签名 -> P-key（用于从前端 JSON 恢复关键点坐标）
FULL_NAME_TO_PKEY: Dict[str, str] = {}
for pkey, short_label in KEYPOINT_MAP.items():
    full_name = LABEL_FULL_NAMES.get(short_label, short_label)
    FULL_NAME_TO_PKEY[full_name] = pkey
    # 同时支持短标签名（兼容性）
    FULL_NAME_TO_PKEY[short_label] = pkey

# 11 点反向映射
FULL_NAME_TO_KEY_11: Dict[str, str] = {}
for key, short_label in KEYPOINT_MAP_11.items():
    full_name = LABEL_FULL_NAMES.get(short_label, short_label)
    FULL_NAME_TO_KEY_11[full_name] = key
    FULL_NAME_TO_KEY_11[short_label] = key

# 34 点反向映射
FULL_NAME_TO_KEY_34: Dict[str, str] = {}
for key, short_label in KEYPOINT_MAP_34.items():
    full_name = LABEL_FULL_NAMES.get(short_label, short_label)
    FULL_NAME_TO_KEY_34[full_name] = key
    FULL_NAME_TO_KEY_34[short_label] = key


def recalculate_ceph_report(
    input_data: Dict[str, Any],
    gender: str,
    dental_age_stage: str,
    pixel_spacing: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    基于客户端修改后的数据重新计算侧位片报告。
    
    Args:
        input_data: 客户端传入的完整推理结果 JSON
        gender: 性别 ("Male" / "Female")
        dental_age_stage: 牙期 ("Permanent" / "Mixed")
        pixel_spacing: 由 API 层解析后的比例尺信息（可选）
    
    Returns:
        重算后的完整报告 JSON (结构与 inference output 一致)
    """
    # ========== 1. 提取 spacing ==========
    if pixel_spacing and pixel_spacing.get("scale_x"):
        spacing_x = pixel_spacing["scale_x"]
        spacing_y = pixel_spacing.get("scale_y", spacing_x)
        spacing_source = pixel_spacing.get("source", "unknown")
    else:
        image_spacing = input_data.get("ImageSpacing")
        if not image_spacing or not image_spacing.get("X"):
            raise ValueError(
                "[PixelSpacing] Neither pixel_spacing parameter nor input_data.ImageSpacing is valid."
            )
        spacing_x = image_spacing.get("X")
        spacing_y = image_spacing.get("Y", spacing_x)
        spacing_source = "input_data"

    spacing = float(spacing_x)
    logger.info(f"[Ceph Recalculate] Spacing: {spacing:.4f} mm/px (Source: {spacing_source})")

    # ========== 2. 提取所有关键点 ==========
    # input_data.LandmarkPositions 可能是扁平列表（旧/重算格式）或嵌套字典（标准格式）
    landmark_positions = input_data.get("LandmarkPositions", {})
    all_input_landmarks: List[Dict[str, Any]] = []

    if isinstance(landmark_positions, list):
        # 极旧格式，直接是列表
        all_input_landmarks = landmark_positions
    elif "Landmarks" in landmark_positions and isinstance(landmark_positions["Landmarks"], list):
        # 扁平结构 (例如上一次重算的结果)
        all_input_landmarks = landmark_positions["Landmarks"]
    else:
        # 标准嵌套结构: CephalometricLandmarks, AirwayLandmarks, ProfileLandmarks
        for group_key in ["CephalometricLandmarks", "AirwayLandmarks", "ProfileLandmarks"]:
            if group_key in landmark_positions:
                all_input_landmarks.extend(landmark_positions[group_key])
    
    # 建立 label -> landmark 索引
    input_by_label: Dict[str, Dict[str, Any]] = {}
    for lm in all_input_landmarks:
        label = lm.get("Label", "")
        input_by_label[label] = lm

    # ========== 3. 分组解析关键点 (25, 11, 34) ==========
    landmarks_25_data = _extract_landmark_group(input_by_label, KEYPOINT_MAP)
    landmarks_11_data = _extract_landmark_group(input_by_label, KEYPOINT_MAP_11)
    landmarks_34_data = _extract_landmark_group(input_by_label, KEYPOINT_MAP_34)

    # ========== 4. 转换坐标为 Numpy 格式用于计算 ==========
    landmarks_25_np = _to_numpy_dict(landmarks_25_data["coordinates"], KEYPOINT_MAP)
    landmarks_11_np = _to_numpy_dict(landmarks_11_data["coordinates"], KEYPOINT_MAP_11)
    # 34点目前主要用于可视化，暂无特定测量计算需求，若有可在此添加

    # ========== 5. 执行计算 ==========
    sex = gender.lower()
    dentition = dental_age_stage.lower()

    # 5.1 基础测量
    measurements = calculate_measurements(
        landmarks=landmarks_25_np,
        sex=sex,
        dentition=dentition,
        spacing=spacing,
    )

    # 5.2 气道与腺体测量 (如果存在 11 点)
    # 判断是否有效检测了气道点 (根据 coordinates 非空判断)
    has_airway_points = len(landmarks_11_data["coordinates"]) > 0
    if has_airway_points:
        airway_result = calculate_airway_measurements(
            landmarks_25=landmarks_25_np,
            landmarks_11=landmarks_11_np,
            spacing=spacing,
        )
        adenoid_result = calculate_adenoid_ratio(
            landmarks_25=landmarks_25_np,
            landmarks_11=landmarks_11_np,
            spacing=spacing,
        )
        measurements["Airway_Gap"] = airway_result
        measurements["Adenoid_Index"] = adenoid_result

    # 5.3 颈椎成熟度 (CVM) 透传处理
    # 尝试从输入测量值中找到 CVSM
    input_measurements_root = input_data.get("Measurements", {})
    cvm_entry = None
    
    # 兼容两种输入结构：
    # 1. 标准结构: Measurements -> BoneAgeMeasurements -> List
    if "BoneAgeMeasurements" in input_measurements_root:
        for entry in input_measurements_root["BoneAgeMeasurements"]:
            if entry.get("Label") == "Cervical_Vertebral_Maturity_Stage":
                cvm_entry = entry
                break
    
    # 2. 扁平结构: CephalometricMeasurements -> AllMeasurements
    if not cvm_entry and "CephalometricMeasurements" in input_data:
        # 旧逻辑可能放在这里
        pass # 通常重算输入如果是标准结构，不会走这里；如果是旧结构，可能也没有 BoneAgeMeasurements
    
    # 3. 兜底：直接在所有测量值中递归查找 (简单起见，假设在 BoneAge 或 Ceph 中)
    if not cvm_entry:
        # 尝试从扁平的 Measurements.CephalometricMeasurements.AllMeasurements 找
        ceph_meas = input_data.get("CephalometricMeasurements", {})
        all_meas = ceph_meas.get("AllMeasurements", [])
        for entry in all_meas:
            if entry.get("Label") == "Cervical_Vertebral_Maturity_Stage":
                cvm_entry = entry
                break
    
    if cvm_entry:
        measurements["Cervical_Vertebral_Maturity_Stage"] = cvm_entry

    # ========== 6. 构建 Inference Results ==========
    inference_results = {
        "landmarks": landmarks_25_data,
        "landmarks_11": landmarks_11_data if has_airway_points else {},
        "landmarks_34": landmarks_34_data if len(landmarks_34_data["coordinates"]) > 0 else {},
        "measurements": measurements,
        "spacing": spacing,
    }

    # ========== 7. 生成标准输出 ==========
    patient_info_dict = {
        "gender": gender,
        "DentalAgeStage": dental_age_stage,
    }
    
    auto_ruler = input_data.get("auto_ruler")

    output_data = generate_standard_output(
        inference_results=inference_results,
        patient_info=patient_info_dict,
        auto_ruler_result=auto_ruler,
        visualization_enabled=True # 重算通常需要可视化数据
    )

    return output_data


def _extract_landmark_group(
    input_by_label: Dict[str, Dict[str, Any]],
    key_map: Dict[str, str]
) -> Dict[str, Any]:
    """
    从输入中提取特定组的关键点，构建 coordinates 和 confidences 字典。
    
    Returns:
        {
            "coordinates": { "P1": [x, y], ... },
            "confidences": { "P1": 0.99, ... }
        }
    """
    coordinates = {}
    confidences = {}

    for pkey, short_label in key_map.items():
        full_label = LABEL_FULL_NAMES.get(short_label, short_label)
        
        # 尝试通过完整名或简称查找
        lm = input_by_label.get(full_label) or input_by_label.get(short_label)
        
        if lm:
            x = lm.get("X")
            y = lm.get("Y")
            confidence = lm.get("Confidence", 0.0)
            status = lm.get("Status", "Missing")
            
            if x is not None and y is not None and status == "Detected":
                coordinates[pkey] = [float(x), float(y)]
                confidences[pkey] = float(confidence)
            else:
                # Missing points are not added to coordinates dict in inference pipeline usually,
                # or handled gracefully. generate_standard_output checks `_is_valid_point`.
                # We can store None or skip. 
                # inference pipeline stores [x,y] or nothing?
                # looking at `_build_landmark_section`: `coord = coordinates.get(key)`
                # so if missing, just don't add to coordinates dict.
                pass
                
    return {
        "coordinates": coordinates,
        "confidences": confidences
    }


def _to_numpy_dict(coordinates: Dict[str, List[float]], key_map: Dict[str, str]) -> Dict[str, np.ndarray]:
    """将坐标字典转换为 Numpy 字典，补全缺失点为 NaN"""
    numpy_dict = {}
    for pkey in key_map.keys():
        if pkey in coordinates:
            numpy_dict[pkey] = np.array(coordinates[pkey])
        else:
            numpy_dict[pkey] = np.array([np.nan, np.nan])
    return numpy_dict
