"""Cephalometric measurement helpers."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import numpy as np

logger = logging.getLogger(__name__)

KEYPOINT_MAP = {
    "P1":  "S",
    "P2":  "N",
    "P3":  "Or",
    "P4":  "Po",
    "P5":  "A",
    "P6":  "B",
    "P7":  "Pog",
    "P8":  "Me",
    "P9":  "Gn",
    "P10": "Go",
    "P11": "L1",
    "P12": "UI",
    "P13": "Bo",
    "P14": "Pt",
    "P15": "ANS",
    "P16": "PNS",
    "P17": "PNS",
    "P18": "ANS",
    "P19": "Ar",
    "P20": "Ba",
    "P21": "Co",
    "P22": "PTM",
    "P23": "U6",
    "P24": "L6",
    "P25": "U1A"
}

ANB_SKELETAL_II_THRESHOLD = 6.0
ANB_SKELETAL_III_THRESHOLD = 2.0
FH_MP_HIGH_ANGLE_THRESHOLD = 33.0
FH_MP_LOW_ANGLE_THRESHOLD = 25.0
SGO_NME_HORIZONTAL_THRESHOLD = 71.0
SGO_NME_VERTICAL_THRESHOLD = 63.0

def calculate_measurements(landmarks: Dict[str, np.ndarray]) -> Dict[str, Dict[str, Any]]:
    """
    Derive cephalometric measurements from landmark coordinates.
    """
    measurements: Dict[str, Dict[str, Any]] = {}

    measurements["ANB_Angle"] = _compute_anb(landmarks)
    measurements["FH_MP_Angle"] = _compute_fh_mp(landmarks)
    measurements["SGo_NMe_Ratio-1"] = _compute_sgo_nme(landmarks)

    return measurements

def _compute_anb(landmarks: Dict[str, np.ndarray]) -> Dict[str, Any]:
    required = ["P1", "P2", "P5", "P6"]
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)

    p1, p2, p5, p6 = (landmarks[idx] for idx in required)
    v_ns = p1 - p2
    v_na = p5 - p2
    v_nb = p6 - p2

    sna = _calculate_angle(v_ns, v_na)
    snb = _calculate_angle(v_ns, v_nb)
    anb = sna - snb

    return {
        "value": float(anb),
        "unit": "degrees",
        "SNA": float(sna),
        "SNB": float(snb),
        "conclusion": _get_skeletal_class(anb),
        "status": "ok",
    }

def _compute_fh_mp(landmarks: Dict[str, np.ndarray]) -> Dict[str, Any]:
    required = ["P3", "P4", "P8", "P10"]
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)

    p3, p4, p8, p10 = (landmarks[idx] for idx in required)
    v_fh = p3 - p4  # Po -> Or
    v_mp = p8 - p10  # Go -> Me
    fh_mp = abs(_calculate_angle(v_fh, v_mp))
    if fh_mp > 90:
        fh_mp = 180 - fh_mp

    return {
        "value": float(fh_mp),
        "unit": "degrees",
        "conclusion": _get_growth_type(fh_mp),
        "status": "ok",
    }

def _compute_sgo_nme(landmarks: Dict[str, np.ndarray]) -> Dict[str, Any]:
    required = ["P1", "P2", "P8", "P10"]
    if not _has_points(landmarks, required):
        return _missing_measurement("%", required, landmarks)

    p1, p2, p8, p10 = (landmarks[idx] for idx in required)
    dist_s_go = np.linalg.norm(p1 - p10)
    dist_n_me = np.linalg.norm(p2 - p8)
    ratio = (dist_s_go / dist_n_me) * 100 if dist_n_me != 0 else 0.0

    return {
        "value": float(ratio),
        "unit": "%",
        "S-Go (px)": float(dist_s_go),
        "N-Me (px)": float(dist_n_me),
        "conclusion": _get_growth_pattern(ratio),
        "status": "ok",
    }

def _has_points(landmarks: Dict[str, np.ndarray], required: List[str]) -> bool:
    missing = [pt for pt in required if pt not in landmarks or _is_nan(landmarks[pt])]
    if missing:
        logger.warning("Missing landmarks for measurement: %s", missing)
        return False
    return True

def _is_nan(point: np.ndarray) -> bool:
    return np.isnan(point).any()

def _missing_measurement(unit: str, required: List[str], landmarks: Dict[str, np.ndarray]) -> Dict[str, Any]:
    missing = [pt for pt in required if pt not in landmarks or _is_nan(landmarks[pt])]
    return {
        "value": None,
        "unit": unit,
        "status": "missing_landmarks",
        "missing": missing,
    }

def _calculate_angle(v1: np.ndarray, v2: np.ndarray) -> float:
    angle = np.degrees(np.arctan2(v2[1], v2[0]) - np.arctan2(v1[1], v1[0]))
    if angle > 180:
        angle -= 360
    elif angle <= -180:
        angle += 360
    return angle

def _get_skeletal_class(anb: float) -> int:
    """返回骨性分类 Level (确保返回 Python 原生 int 类型)"""
    # 确保 anb 是 Python float 类型
    anb_float = float(anb)
    if anb_float > ANB_SKELETAL_II_THRESHOLD:
        return int(1)  # 骨性II类
    if anb_float < ANB_SKELETAL_III_THRESHOLD:
        return int(2)  # 骨性III类
    return int(0)  # 骨性I类

def _get_growth_type(fh_mp: float) -> int:
    """返回生长型 Level (确保返回 Python 原生 int 类型)"""
    # 确保 fh_mp 是 Python float 类型
    fh_mp_float = float(fh_mp)
    if fh_mp_float > FH_MP_HIGH_ANGLE_THRESHOLD:
        return int(1)  # 高角
    if fh_mp_float < FH_MP_LOW_ANGLE_THRESHOLD:
        return int(2)  # 低角
    return int(0)  # 均角

def _get_growth_pattern(sgo_nme: float) -> int:
    """返回生长模式 Level (确保返回 Python 原生 int 类型)"""
    # 确保 sgo_nme 是 Python float 类型
    sgo_nme_float = float(sgo_nme)
    if sgo_nme_float > SGO_NME_HORIZONTAL_THRESHOLD:
        return int(1)  # 水平生长型
    if sgo_nme_float < SGO_NME_VERTICAL_THRESHOLD:
        return int(2)  # 垂直生长型
    return int(0)  # 平均生长型
