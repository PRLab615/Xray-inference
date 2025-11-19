"""Cephalometric measurement helpers."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import numpy as np

logger = logging.getLogger(__name__)

KEYPOINT_MAP = {
    "P1": "Sella (S)",
    "P2": "Nasion (N)",
    "P3": "Orbitale (Or)",
    "P4": "Porion (Po)",
    "P5": "Subspinale (A)",
    "P6": "Supramentale (B)",
    "P7": "Pogonion (Pog)",
    "P8": "Menton (Me)",
    "P9": "Gnathion (Gn)",
    "P10": "Gonion (Go)",
    "P11": "Incision inferius (L1)",
    "P12": "Incision superius (U1)",
    "P13": "Upper lip",
    "P14": "Lower lip",
    "P15": "Subnasale",
    "P16": "Soft tissue pogonion",
    "P17": "Posterior nasal spine (PNS)",
    "P18": "Anterior nasal spine (ANS)",
    "P19": "Articulare (Ar)",
}

ANB_SKELETAL_II_THRESHOLD = 6.0
ANB_SKELETAL_III_THRESHOLD = 1.0
FH_MP_HIGH_ANGLE_THRESHOLD = 34.0
FH_MP_LOW_ANGLE_THRESHOLD = 24.0
SGO_NME_HORIZONTAL_THRESHOLD = 71.0
SGO_NME_VERTICAL_THRESHOLD = 62.0

def calculate_measurements(landmarks: Dict[str, np.ndarray]) -> Dict[str, Dict[str, Any]]:
    """
    Derive cephalometric measurements from landmark coordinates.
    """
    measurements: Dict[str, Dict[str, Any]] = {}

    measurements["ANB_Angle"] = _compute_anb(landmarks)
    measurements["FH_MP_Angle"] = _compute_fh_mp(landmarks)
    measurements["SGo_NMe_Ratio"] = _compute_sgo_nme(landmarks)

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

def _get_skeletal_class(anb: float) -> str:
    if anb > ANB_SKELETAL_II_THRESHOLD:
        return "骨性II类"
    if anb < ANB_SKELETAL_III_THRESHOLD:
        return "骨性III类"
    return "骨性I类"

def _get_growth_type(fh_mp: float) -> str:
    if fh_mp > FH_MP_HIGH_ANGLE_THRESHOLD:
        return "高角"
    if fh_mp < FH_MP_LOW_ANGLE_THRESHOLD:
        return "低角"
    return "均角"

def _get_growth_pattern(sgo_nme: float) -> str:
    if sgo_nme > SGO_NME_HORIZONTAL_THRESHOLD:
        return "水平生长型"
    if sgo_nme < SGO_NME_VERTICAL_THRESHOLD:
        return "垂直生长型"
    return "平均生长型"
