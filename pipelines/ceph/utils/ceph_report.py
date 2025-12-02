"""Cephalometric measurement helpers."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import numpy as np

logger = logging.getLogger(__name__)

KEYPOINT_MAP = {
    "P1": "S",
    "P2": "N",
    "P3": "Or",
    "P4": "Po",
    "P5": "A",
    "P6": "B",
    "P7": "Pog",
    "P8": "Me",
    "P9": "Gn",
    "P10": "Go",
    "P11": "L1",
    "P12": "UI",
    "P13": "PNS",
    "P14": "ANS",
    "P15": "Ar",
    "P16": "Co",
    "P17": "PTM",
    "P18": "Pt",
    "P19": "U1A",
    "P20": "L1A",
    "P21": "U6",
    "P22": "L6",
    "P23": "Ba",
    "P24": "Bo",
    "P25": "Pcd"
}

ANB_SKELETAL_II_THRESHOLD = 6.0
ANB_SKELETAL_III_THRESHOLD = 2.0
FH_MP_HIGH_ANGLE_THRESHOLD = 33.0
FH_MP_LOW_ANGLE_THRESHOLD = 25.0
SGO_NME_HORIZONTAL_THRESHOLD = 71.0
SGO_NME_VERTICAL_THRESHOLD = 63.0

# 新增


THRESHOLDS = {

    "ANB": {
        "male": {"mixed": (2.0, 6.0), "permanent": (2.0, 6.0), "all": (2.0, 6.0)},
        "female": {"mixed": (2.0, 6.0), "permanent": (1.0, 5.0)},
    },

    # 长度类（mean, std）
    "PtmANS_Length": {
        "male": {"mixed": (47.2, 2.2), "permanent": (50.4, 4.1)},
        "female": {"mixed": (44.8, 2.0), "permanent": (47.7, 2.9)},
    },
    "GoPo_Length": {
        "male": {"mixed": (68.0, 4.0), "permanent": (74.0, 5.0)},
        "female": {"mixed": (68.0, 4.0), "permanent": (73.0, 4.0)},
    },
    "PoNB_Length": {
        "male": {"mixed": (0.2, 1.3), "permanent": (1.0, 1.5)},
        "female": {"mixed": (0.2, 1.3), "permanent": (1.0, 1.5)},
    },
    "Upper_Jaw_Position": {
        "male": {"mixed": (18.0, 2.0), "permanent": (17.0, 3.0)},
        "female": {"mixed": (17.0, 2.0), "permanent": (18.0, 2.0)},
    },
    "Pcd_Lower_Position": {
        "male": {"mixed": (16.0, 3.0), "permanent": (19.0, 3.0)},
        "female": {"mixed": (16.0, 2.0), "permanent": (17.0, 3.0)},
    },

    # 角度类（mean, std）
    "FH_MP_Angle": {
        "male": {"mixed": (28.0, 4.0), "permanent": (29.0, 4.0)},
        "female": {"mixed": (30.0, 4.0), "permanent": (28.0, 4.0)},
    },
    "UI_SN_Angle": {
        "male": {"mixed": (107.0, 5.0), "permanent": (107.0, 6.0)},
        "female": {"mixed": (106.0, 6.0), "permanent": (105.0, 6.0)},
    },
    "IMPA_Angle": {
        "male": {"mixed": (94.7, 5.2), "permanent": (92.6, 7.0)},
        "female": {"mixed": (94.7, 5.2), "permanent": (92.6, 7.0)},
    },
    "SNA": {
        "male": {"mixed": (82.0, 3.0), "permanent": (84.0, 3.0)},
        "female": {"mixed": (82.0, 4.0), "permanent": (83.0, 4.0)},
    },

    "SNB": {
        "male": {"mixed": (78.0, 3.0), "permanent": (80.0, 3.0)},
        "female": {"mixed": (78.0, 4.0), "permanent": (79.0, 3.0)},
    },

    # 比例类（mean, std）S-Go/N-Me %
    "SGo_NMe_Ratio": {
        "male": {"mixed": (65.0, 4.0), "permanent": (67.0, 4.0)},
        "female": {"mixed": (64.0, 4.0), "permanent": (66.0, 4.0)},
    },

    "Y_Axis_Angle": {
        "male": {"mixed": (63.0, 4.0), "permanent": (65.0, 4.0)},
        "female": {"mixed": (65.0, 3.0), "permanent": (64.0, 3.0)},
    },
    "SN_MP_Angle": {
        "male": {"mixed": (35.0, 4.0), "permanent": (35.0, 4.0)},
        "female": {"mixed": (35.0, 4.0), "permanent": (33.0, 4.0)},
    },
    "Upper_Anterior_Alveolar_Height": {  # U1-PP
        "male": {"mixed": (27.0, 2.0), "permanent": (28.0, 3.0)},
        "female": {"mixed": (26.0, 2.0), "permanent": (28.0, 2.0)},
    },
    "L1_MP_Lower_Anterior_Alveolar_Height": {  # L1-MP
        "male": {"mixed": (38.0, 2.0), "permanent": (42.0, 3.0)},
        "female": {"mixed": (38.0, 2.0), "permanent": (40.0, 2.0)},
    },
    "U6_PP_Upper_Posterior_Alveolar_Height": {  # U6-PP
        "male": {"mixed": (19.0, 2.0), "permanent": (22.0, 2.0)},
        "female": {"mixed": (19.0, 2.0), "permanent": (22.0, 2.0)},
    },
    "L6_MP_Lower_Posterior_Alveolar_Height": {  # L6-MP
        "male": {"mixed": (31.0, 2.0), "permanent": (35.0, 3.0)},
        "female": {"mixed": (30.0, 2.0), "permanent": (33.0, 2.0)},
    },
    "Distance_Witsmm": {
        "male": {"mixed": (-1.4, 2.6), "permanent": (-1.4, 2.9)},
        "female": {"mixed": (-1.4, 2.8), "permanent": (-1.1, 2.9)},
    },
    "U1_NA_Angle": {
        "male": {"mixed": (25.0, 5.0), "permanent": (24.0, 6.0)},
        "female": {"mixed": (24.0, 5.0), "permanent": (21.0, 6.0)},
    },
    "U1_NA_Incisor_Length": {
        "male": {"mixed": (4.0, 2.0), "permanent": (4.0, 2.0)},
        "female": {"mixed": (4.0, 2.0), "permanent": (4.0, 2.0)},
    },
    "FMIA_Angle": {
        "male": {"mixed": (54.0, 6.0), "permanent": (52.0, 7.0)},
        "female": {"mixed": (53.0, 6.0), "permanent": (57.0, 7.0)},
    },
    "L1_NB_Angle": {
        "male": {"mixed": (30.0, 6.0), "permanent": (32.0, 6.0)},
        "female": {"mixed": (30.0, 6.0), "permanent": (28.0, 6.0)},
    },
    "L1_NB_Distance": {
        "male": {"mixed": (6.0, 2.0), "permanent": (7.0, 3.0)},
        "female": {"mixed": (6.0, 2.0), "permanent": (6.0, 2.0)},
    },
    "U1_L1_Inter_Incisor_Angle": {
        "male": {"mixed": (121.0, 8.0), "permanent": (121.0, 9.0)},
        "female": {"mixed": (122.0, 8.0), "permanent": (127.0, 9.0)},
    },
    "Mandibular_Growth_Angle": {  # Face Axis (NBa-PTGn)
        "male": {"mixed": (88.0, 4.0), "permanent": (87.0, 4.0)},
        "female": {"mixed": (87.0, 3.0), "permanent": (88.0, 3.0)},
    },
    "S_N_Anterior_Cranial_Base_Length": {
        "male": {"mixed": (66.7, 3.9), "permanent": (66.7, 3.9)},
        "female": {"mixed": (63.7, 4.8), "permanent": (63.7, 4.8)},
    },
    "Go_Me_Length": {
        "male": {"mixed": (78.2, 5.0), "permanent": (78.2, 5.0)},
        "female": {"mixed": (72.8, 3.6), "permanent": (72.8, 3.6)},
    },
    "Mandibular_Growth_Type_Angle": {  # Bjork sum
        "male": {"mixed": (396.0, 6.0), "permanent": (396.0, 6.0)},
        "female": {"mixed": (396.0, 6.0), "permanent": (396.0, 6.0)},
    },
}


SNA_MIN, SNA_MAX = 81.0, 87.0
SNB_MIN, SNB_MAX = 77.0, 83.0
U1_SN_MIN, U1_SN_MAX = 101.0, 113.0
IMPA_MIN, IMPA_MAX = 85.6, 99.6
U1_NA_ANGLE_MIN, U1_NA_ANGLE_MAX = 18.0, 30.0
U1_NA_MM_MIN, U1_NA_MM_MAX = 2.0, 6.0
L1_NB_ANGLE_MIN, L1_NB_ANGLE_MAX = 26.0, 38.0
L1_NB_MM_MIN, L1_NB_MM_MAX = 4.0, 10.0
INTERINCISOR_MIN, INTERINCISOR_MAX = 112.0, 130.0
FACE_AXIS_MIN, FACE_AXIS_MAX = 83.0, 91.0
BJORK_SUM_MIN, BJORK_SUM_MAX = 390.0, 402.0

def calculate_measurements(landmarks: Dict[str, np.ndarray], sex: str = "male", dentition: str = "permanent"   ) -> Dict[str, Dict[str, Any]]:
    """
    Derive cephalometric measurements from landmark coordinates.
    """
    measurements: Dict[str, Dict[str, Any]] = {}

    sex = sex.lower()
    dentition = dentition.lower()
    if dentition not in ("mixed", "permanent", "all"):
        # 兜底：允许 'all' 用于 ANB male 全周期情况
        dentition = "permanent"

    # 新增：使用 sex/dentition 判别阈值的测量项（尽量保留原返回结构）
    measurements["ANB_Angle"] = _compute_anb(landmarks, sex=sex, dentition=dentition)
    measurements["FH_MP_Angle"] = _compute_fh_mp(landmarks, sex=sex, dentition=dentition)
    measurements["SGo_NMe_Ratio-1"] = _compute_sgo_nme(landmarks, sex=sex, dentition=dentition)

    # 新增：使用 sex/dentition 判别阈值的测量项（尽量保留原返回结构）
    measurements["PtmANS_Length"] = _compute_ptmans_length(landmarks, sex=sex, dentition=dentition)
    measurements["GoPo_Length"] = _compute_gopo_length(landmarks, sex=sex, dentition=dentition)
    measurements["PoNB_Length"] = _compute_ponb_length(landmarks, sex=sex, dentition=dentition)
    measurements["SNA_Angle"] = _compute_sna(landmarks, sex=sex, dentition=dentition)
    measurements["SNB_Angle"] = _compute_snb(landmarks, sex=sex, dentition=dentition)
    measurements["Upper_Jaw_Position"] = _compute_ptm_s(landmarks, sex=sex, dentition=dentition)
    measurements["Pcd_Lower_Position"] = _compute_pcd_s(landmarks, sex=sex, dentition=dentition)
    measurements["Distance_Witsmm"] = _compute_wits(landmarks, sex=sex, dentition=dentition)
    measurements["UI_SN_Angle"] = _compute_u1_sn(landmarks, sex=sex, dentition=dentition)
    measurements["IMPA_Angle-1"] = _compute_impa(landmarks, sex=sex, dentition=dentition)
    measurements["Upper_Anterior_Alveolar_Height"] = _compute_u1_pp(landmarks, sex=sex, dentition=dentition)
    measurements["U1_NA_Angle"] = _compute_u1_na_angle(landmarks, sex=sex, dentition=dentition)
    measurements["U1_NA_Incisor_Length"] = _compute_u1_na_mm(landmarks, sex=sex, dentition=dentition)
    measurements["FMIA_Angle"] = _compute_fmia(landmarks, sex=sex, dentition=dentition)
    measurements["L1_NB_Angle"] = _compute_l1_nb_angle(landmarks, sex=sex, dentition=dentition)
    measurements["L1_NB_Distance"] = _compute_l1_nb_mm(landmarks, sex=sex, dentition=dentition)
    measurements["U1_L1_Inter_Incisor_Angle"] = _compute_interincisor_angle(landmarks, sex=sex, dentition=dentition)
    measurements["Mandibular_Growth_Angle"] = _compute_face_axis(landmarks, sex=sex, dentition=dentition)
    measurements["S_N_Anterior_Cranial_Base_Length"] = _compute_s_n_length(landmarks, sex=sex, dentition=dentition)
    measurements["Go_Me_Length"] = _compute_go_me_length(landmarks, sex=sex, dentition=dentition)
    measurements["U1_SN_Angle_Repeat"] = _compute_u1_sn_repeat(landmarks, sex=sex, dentition=dentition)
    measurements["IMPA_Angle-2"] = _compute_impa_2(landmarks, sex=sex, dentition=dentition)
    measurements["Y_SGo_NMe_Ratio-2"] = _compute_y_axis_angle(landmarks, sex=sex,dentition=dentition)  # MODIFIED: 原来错误复用 SGo_NMe
    measurements["SGo_NMe_Ratio-3"] = _compute_sgo_nme_ratio_3(landmarks, sex=sex, dentition=dentition)
    measurements["SN_FH_Angle-1"] = _compute_sn_mp_angle(landmarks, sex=sex,dentition=dentition)  # MODIFIED: 改为 SN-MP (S-N 与 Go-Me)
    measurements["MP_FH_Angle-2"] = _compute_fh_mp_repeat(landmarks, sex=sex, dentition=dentition)
    measurements["U1_PP_Upper_Anterior_Alveolar_Height"] = _compute_u1_pp_repeat(landmarks, sex=sex,dentition=dentition)
    measurements["L1_MP_Lower_Anterior_Alveolar_Height"] = _compute_l1_mp_height(landmarks, sex=sex,dentition=dentition)
    measurements["U6_PP_Upper_Posterior_Alveolar_Height"] = _compute_u6_pp_height(landmarks, sex=sex,dentition=dentition)
    measurements["L6_MP_Lower_Posterior_Alveolar_Height"] = _compute_l6_mp_height(landmarks, sex=sex,dentition=dentition)
    measurements["Mandibular_Growth_Type_Angle"] = _compute_mandibular_growth_type_angle(landmarks, sex=sex,dentition=dentition)

    measurements["Jaw_Development_Coordination"] = _compute_jaw_coordination(measurements)

    return measurements

def _compute_anb(landmarks: Dict[str, np.ndarray], sex: str = "male", dentition: str = "permanent") -> Dict[str, Any]:
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

    conclusion_level = _get_skeletal_class(anb, sex=sex, dentition=dentition)  # MODIFIED: 传入 sex/dentition

    return {
        "value": float(anb),
        "unit": "degrees",
        "SNA": float(sna),
        "SNB": float(snb),
        "conclusion": conclusion_level,
        "status": "ok",
    }


def _compute_fh_mp(landmarks: Dict[str, np.ndarray], sex: str = "male", dentition: str = "permanent") -> Dict[str, Any]:
    required = ["P3", "P4", "P8", "P10"]
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)

    p3, p4, p8, p10 = (landmarks[idx] for idx in required)
    v_fh = p3 - p4  # Po -> Or
    v_mp = p8 - p10  # Go -> Me
    fh_mp = abs(_calculate_angle(v_fh, v_mp))
    if fh_mp > 90:
        fh_mp = 180 - fh_mp


    level = _evaluate_by_threshold("FH_MP_Angle", fh_mp, sex, dentition)

    return {
        "value": float(fh_mp),
        "unit": "degrees",
        "conclusion": _get_growth_type(fh_mp) if level == 0 else level,  # 保留原 get_growth_type 的语义兼容
        "status": "ok",
    }

def _compute_sgo_nme(landmarks: Dict[str, np.ndarray], sex: str = "male", dentition: str = "permanent") -> Dict[str, Any]:
    required = ["P1", "P2", "P8", "P10"]
    if not _has_points(landmarks, required):
        return _missing_measurement("%", required, landmarks)

    p1, p2, p8, p10 = (landmarks[idx] for idx in required)
    dist_s_go = np.linalg.norm(p1 - p10)
    dist_n_me = np.linalg.norm(p2 - p8)
    ratio = (dist_s_go / dist_n_me) * 100 if dist_n_me != 0 else 0.0

    level = _evaluate_by_threshold("SGo_NMe_Ratio", ratio, sex, dentition)

    return {
        "value": float(ratio),
        "unit": "%",
        "S-Go (px)": float(dist_s_go),
        "N-Me (px)": float(dist_n_me),
        "conclusion": _get_growth_pattern(ratio) if level == 0 else level,
        "status": "ok",
    }


def _compute_ptmans_length(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P17", "P14"]  # PTM-ANS
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    length = np.linalg.norm(landmarks["P17"] - landmarks["P14"])

    level = _evaluate_by_threshold("PtmANS_Length", length, sex, dentition)
    return {"value": float(length), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_gopo_length(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P10", "P7", "P8"]  # Go-Pog 投影到MP
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    go, pog, me = landmarks["P10"], landmarks["P7"], landmarks["P8"]
    mp_vec = me - go
    proj = np.dot(pog - go, mp_vec) / np.dot(mp_vec, mp_vec)
    length = abs(proj) * np.linalg.norm(mp_vec)
    level = _evaluate_by_threshold("GoPo_Length", length, sex, dentition)  # MODIFIED
    return {"value": float(length), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_ponb_length(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P7", "P2", "P6"]  # Pog 到 NB 的垂直距离
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    pog, n, b = landmarks["P7"], landmarks["P2"], landmarks["P6"]
    nb_vec = b - n
    dist = abs(np.cross(nb_vec, pog - n) / np.linalg.norm(nb_vec))
    # PoNB 可能为正负，绝对值判断是否偏离正常均值
    level = _evaluate_by_threshold("PoNB_Length", float(dist), sex, dentition)
    return {"value": float(dist), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_sna(landmarks, sex: str = "male", dentition: str = "permanent"):
    tmp = _compute_anb(landmarks, sex=sex, dentition=dentition)
    if tmp["status"] != "ok":
        return tmp
    sna = tmp["SNA"]
    level = _evaluate_by_threshold("SNA", sna, sex, dentition)  # MODIFIED: 使用阈值表
    return {"value": float(sna), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_snb(landmarks, sex: str = "male", dentition: str = "permanent"):
    tmp = _compute_anb(landmarks, sex=sex, dentition=dentition)
    if tmp["status"] != "ok":
        return tmp
    snb = tmp["SNB"]
    level = _evaluate_by_threshold("SNB", snb, sex, dentition)  # MODIFIED
    return {"value": float(snb), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_ptm_s(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P17", "P1"]
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    length = np.linalg.norm(landmarks["P17"] - landmarks["P1"])
    level = _evaluate_by_threshold("Upper_Jaw_Position", length, sex, dentition)  # MODIFIED
    return {"value": float(length), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_pcd_s(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P25", "P1"]
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    length = np.linalg.norm(landmarks["P25"] - landmarks["P1"])
    level = _evaluate_by_threshold("Pcd_Lower_Position", length, sex, dentition)  # MODIFIED
    return {"value": float(length), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_wits(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P5", "P6", "P3", "P4"]  # A,B,Or,Po → FH平面
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    a, b, or_pt, po = (landmarks[k] for k in required)
    fh = po - or_pt
    a_proj = np.dot(a - or_pt, fh) / np.dot(fh, fh)
    b_proj = np.dot(b - or_pt, fh) / np.dot(fh, fh)
    wits = (b_proj - a_proj) * np.linalg.norm(fh)
    # Wits 的阈值未在 THRESHOLDS 表中给出，保持原有逻辑：
    level = _evaluate_by_threshold("Distance_Witsmm", wits, sex, dentition)
    return {"value": float(wits), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_u1_sn(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P12", "P19", "P1", "P2"]
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    u1, u1a, s, n = (landmarks[k] for k in required)
    axis = u1a - u1
    sn = s - n
    angle = _angle_between_vectors(axis, sn)
    # 使用阈值表（MODIFIED）
    level = _evaluate_by_threshold("UI_SN_Angle", angle, sex, dentition)
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_impa(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P11", "P20", "P8", "P10"]
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    l1, l1a, me, go = (landmarks[k] for k in required)
    axis = l1a - l1
    mp = me - go
    angle = _angle_between_vectors(axis, mp)
    level = _evaluate_by_threshold("IMPA_Angle", angle, sex, dentition)  # MODIFIED
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_u1_pp(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P12", "P14", "P13"]
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    u1, ans, pns = (landmarks[k] for k in required)
    pp = pns - ans

    # 原阈值保留（没有在 THRESHOLDS 表中）
    dist_scalar = abs(np.cross(pp, u1 - ans) / np.linalg.norm(pp))
    level = _evaluate_by_threshold("Upper_Anterior_Alveolar_Height", dist_scalar, sex, dentition)
    return {"value": float(dist_scalar), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_u1_na_angle(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P12", "P19", "P2", "P5"]
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    u1, u1a, n, a = (landmarks[k] for k in required)
    axis = u1a - u1
    na = a - n
    angle = _angle_between_vectors(axis, na)
    level = _evaluate_by_threshold("U1_NA_Angle", angle, sex, dentition)
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_u1_na_mm(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P12", "P2", "P5"]
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    u1, n, a = landmarks["P12"], landmarks["P2"], landmarks["P5"]
    na = a - n
    dist_scalar = abs(np.cross(na, u1 - n) / np.linalg.norm(na))
    level = _evaluate_by_threshold("U1_NA_Incisor_Length", dist_scalar, sex, dentition)
    return {"value": float(dist_scalar), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_fmia(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P11", "P20", "P3", "P4"]
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    l1, l1a, or_pt, po = (landmarks[k] for k in required)
    axis = l1a - l1
    fh = po - or_pt
    angle = _angle_between_vectors(axis, fh)
    level = _evaluate_by_threshold("FMIA_Angle", angle, sex, dentition)
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_l1_nb_angle(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P11", "P20", "P2", "P6"]
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    l1, l1a, n, b = (landmarks[k] for k in required)
    axis = l1a - l1
    nb = b - n
    angle = _angle_between_vectors(axis, nb)
    level = _evaluate_by_threshold("L1_NB_Angle", angle, sex, dentition)
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_l1_nb_mm(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P11", "P2", "P6"]
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    l1, n, b = landmarks["P11"], landmarks["P2"], landmarks["P6"]
    nb = b - n

    dist_scalar = abs(np.cross(nb, l1 - n) / np.linalg.norm(nb))
    level = _evaluate_by_threshold("L1_NB_Distance", dist_scalar, sex, dentition)
    return {"value": float(dist_scalar), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_interincisor_angle(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P12", "P19", "P11", "P20"]
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    u_axis = landmarks["P19"] - landmarks["P12"]
    l_axis = landmarks["P20"] - landmarks["P11"]
    angle = _angle_between_vectors(u_axis, l_axis)
    level = _evaluate_by_threshold("U1_L1_Inter_Incisor_Angle", angle, sex, dentition)
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_face_axis(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P23", "P2", "P18", "P9"]  # Ba,N,Pt,Gn
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    ba, n, pt, gn = (landmarks[k] for k in required)
    n_ba = ba - n
    pt_gn = gn - pt
    angle = _angle_between_vectors(n_ba, pt_gn)
    level = _evaluate_by_threshold("Mandibular_Growth_Angle", angle, sex, dentition)
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_s_n_length(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P1", "P2"]
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    length = np.linalg.norm(landmarks["P1"] - landmarks["P2"])
    level = _evaluate_by_threshold("S_N_Anterior_Cranial_Base_Length", length, sex, dentition)
    return {"value": float(length), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_go_me_length(landmarks, sex: str = "male", dentition: str = "permanent"):
    required = ["P10", "P8"]
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    length = np.linalg.norm(landmarks["P10"] - landmarks["P8"])
    level = _evaluate_by_threshold("Go_Me_Length", length, sex, dentition)
    return {"value": float(length), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_jaw_coordination(measurements):
    upper = measurements.get("SNA_Angle", {}).get("conclusion", 0)
    if upper == 0:
        upper = measurements.get("PtmANS_Length", {}).get("conclusion", 0)
    lower = measurements.get("SNB_Angle", {}).get("conclusion", 0)
    return {"value": [upper, lower], "unit": "multi", "conclusion": [upper, lower], "status": "ok"}

def _compute_u1_sn_repeat(landmarks, sex: str = "male", dentition: str = "permanent"):
    """第18项：U1-SN角度重复测量（与UI_SN_Angle完全相同，但独立计算）"""
    required = ["P12", "P19", "P1", "P2"]
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    u1, u1a, s, n = (landmarks[k] for k in required)
    axis = u1a - u1
    sn = s - n
    angle = _angle_between_vectors(axis, sn)
    level = _evaluate_by_threshold("UI_SN_Angle", angle, sex, dentition)  # MODIFIED: 使用阈值表
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_impa_2(landmarks, sex: str = "male", dentition: str = "permanent"):
    """第21项：IMPA角度重复测量（与IMPA_Angle-1完全相同，但独立计算）"""
    required = ["P11", "P20", "P8", "P10"]
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    l1, l1a, me, go = (landmarks[k] for k in required)
    axis = l1a - l1
    mp = me - go
    angle = _angle_between_vectors(axis, mp)
    level = _evaluate_by_threshold("IMPA_Angle", angle, sex, dentition)  # MODIFIED
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_sgo_nme_ratio_2(landmarks, sex: str = "male", dentition: str = "permanent"):
    """第26项：SGo/NMe比例重复测量（与SGo_NMe_Ratio-1完全相同）"""
    return _compute_sgo_nme(landmarks, sex=sex, dentition=dentition)  # 复用，传入 sex/dentition

def _compute_sgo_nme_ratio_3(landmarks, sex: str = "male", dentition: str = "permanent"):
    """第28项：SGo/NMe比例再次重复测量"""
    return _compute_sgo_nme(landmarks, sex=sex, dentition=dentition)

def _compute_sn_fh_angle(landmarks):

    required = ["P1", "P2", "P3", "P4"]  # S, N, Or, Po
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    S, N, Or, Po = (landmarks[k] for k in required)
    sn_vec = N - S
    fh_vec = Po - Or
    angle = _angle_between_vectors(sn_vec, fh_vec)
    if angle > 90:
        angle = 180 - angle
    # 原逻辑：
    if angle > 9.0:
        level = 1
    elif angle < 5.0:
        level = 2
    else:
        level = 0
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_sn_mp_angle(landmarks, sex: str = "male", dentition: str = "permanent"):
    """第29项：SN-MP角（S-N平面与下颌平面(Go-Me)的夹角）"""
    required = ["P1", "P2", "P10", "P8"]  # S, N, Go, Me
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)

    S, N, Go, Me = (landmarks[k] for k in required)

    # SN 向量（S→N）
    sn_vec = N - S
    # MP 向量（Go→Me）
    mp_vec = Me - Go

    angle = _angle_between_vectors(sn_vec, mp_vec)
    if angle > 90:
        angle = 180 - angle

    # 使用阈值表（若没有则调用 _get_growth_type 作为回退）
    level = _evaluate_by_threshold("SN_MP_Angle", angle, sex, dentition)
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_fh_mp_repeat(landmarks, sex: str = "male", dentition: str = "permanent"):
    """第30项：FH-MP角度重复测量（与FH_MP_Angle完全相同，但独立计算）"""
    return _compute_fh_mp(landmarks, sex=sex, dentition=dentition)  # 直接复用

def _compute_u1_pp_repeat(landmarks, sex: str = "male", dentition: str = "permanent"):
    """第31项：上前牙槽高度重复测量（与Upper_Anterior_Alveolar_Height完全相同）"""
    return _compute_u1_pp(landmarks, sex=sex, dentition=dentition)

def _compute_l1_mp_height(landmarks, sex: str = "male", dentition: str = "permanent"):
    """第33项：下前牙槽高度 L1切缘到下颌平面（Go-Me）的垂直距离"""
    required = ["P11", "P10", "P8"]  # L1, Go, Me
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    l1, go, me = landmarks["P11"], landmarks["P10"], landmarks["P8"]
    mp_vec = me - go
    dist = abs(np.cross(mp_vec, l1 - go)[0] / np.linalg.norm(mp_vec))
    level = _evaluate_by_threshold("L1_MP_Lower_Anterior_Alveolar_Height", dist, sex, dentition)
    return {"value": float(dist), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_u6_pp_height(landmarks, sex: str = "male", dentition: str = "permanent"):
    """第34项：上后牙槽高度 U6到腭平面（ANS-PNS）的垂直距离"""
    required = ["P21", "P14", "P13"]  # U6, ANS, PNS
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    u6, ans, pns = landmarks["P21"], landmarks["P14"], landmarks["P13"]
    pp_vec = pns - ans
    dist = abs(np.cross(pp_vec, u6 - ans)[0] / np.linalg.norm(pp_vec))
    level = _evaluate_by_threshold("U6_PP_Upper_Posterior_Alveolar_Height", dist, sex, dentition)
    return {"value": float(dist), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_l6_mp_height(landmarks, sex: str = "male", dentition: str = "permanent"):
    """第35项：下后牙槽高度 L6到下颌平面（Go-Me）的垂直距离"""
    required = ["P22", "P10", "P8"]  # L6, Go, Me
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    l6, go, me = landmarks["P22"], landmarks["P10"], landmarks["P8"]
    mp_vec = me - go
    dist = abs(np.cross(mp_vec, l6 - go)[0] / np.linalg.norm(mp_vec))
    level = _evaluate_by_threshold("L6_MP_Lower_Posterior_Alveolar_Height", dist, sex, dentition)
    return {"value": float(dist), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_mandibular_growth_type_angle(landmarks, sex: str = "male", dentition: str = "permanent"):
    """
    Mandibular_Growth_Type_Angle（Björk Sum 正确版）
    = 鞍角(N-S-Ar) + 关节角(S-Ar-Go) + 下颌角(Ar-Go-Me) + 下颌平面角(SN-MP)
    正常范围：390.0–402.0°
    """
    required = ["P1", "P2", "P15", "P10", "P8"]  # S, N, Ar, Go, Me
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)

    S  = landmarks["P1"]
    N  = landmarks["P2"]
    Ar = landmarks["P15"]
    Go = landmarks["P10"]
    Me = landmarks["P8"]

    # 1. 鞍角 Saddle angle ∠N-S-Ar
    angle1 = _angle_between_vectors(S - N, Ar - S)

    # 2. 关节角 Articular angle ∠S-Ar-Go
    angle2 = _angle_between_vectors(Ar - S, Go - Ar)

    # 3. 下颌角 Gonial angle ∠Ar-Go-Me
    angle3 = _angle_between_vectors(Go - Ar, Me - Go)

    # 4. 下颌平面角 SN-MP ∠(S-N 与 Go-Me)
    sn_vec = S - N
    mp_vec = Me - Go
    angle4 = _angle_between_vectors(sn_vec, mp_vec)

    total = angle1 + angle2 + angle3 + angle4

    # Level 判断（与PPT完全一致）
    level = _evaluate_by_threshold("Mandibular_Growth_Type_Angle", total, sex, dentition)

    return {
        "value": float(total),
        "unit": "degrees",
        "details": {
            "Saddle_angle_N_S_Ar": float(angle1),
            "Articular_angle_S_Ar_Go": float(angle2),
            "Gonial_angle_Ar_Go_Me": float(angle3),
            "Mandibular_plane_angle_SN_MP": float(angle4),
        },
        "conclusion": level,
        "status": "ok"
    }


def _compute_y_axis_angle(landmarks, sex: str = "male", dentition: str = "permanent"):
    """
    Y轴角 (Y-axis angle) — 独立生长型指标
    常规定义示例：Sella（S）到 Gnathion（Gn）方向与 Frankfort 平面 (Or-Po) 的夹角
    这里实现为： ∠(S→Gn, Or→Po) 的夹角（0~180）
    """
    required = ["P1", "P9", "P3", "P4"]  # S, Gn, Or, Po
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)

    S = landmarks["P1"]
    Gn = landmarks["P9"]
    Or = landmarks["P3"]
    Po = landmarks["P4"]

    v_y = Gn - S
    v_fh = Po - Or
    angle = _angle_between_vectors(v_y, v_fh)
    # 角度范围调整
    if angle > 90:
        angle = 180 - angle

    # Y轴角没有在 THRESHOLDS 定义，暂时使用简单判别：>?? 未定义 -> 返回 0
    level = _evaluate_by_threshold("Y_Axis_Angle", angle, sex, dentition)
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}




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

def _get_skeletal_class(anb: float, sex: str = "male", dentition: str = "permanent") -> int:
    """返回骨性分类 Level (确保返回 Python 原生 int 类型)
    MODIFIED: 根据 sex 和 dentition 使用 THRESHOLDS["ANB"] 动态区间判断
    """
    anb_float = float(anb)
    level = _evaluate_by_threshold("ANB", anb_float, sex, dentition)
    # 将 0/1/2 对应为 0=I,1=II,2=III
    return int(level)

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

def _angle_between_vectors(v1: np.ndarray, v2: np.ndarray) -> float:
    """计算两个向量之间的夹角（0~180°），角度测量"""
    dot = np.dot(v1, v2)
    norm = np.linalg.norm(v1) * np.linalg.norm(v2)
    if norm == 0:
        return 0.0
    cos_theta = np.clip(dot / norm, -1.0, 1.0)
    angle = np.degrees(np.arccos(cos_theta))
    return float(angle)

def _evaluate_by_threshold(feature: str, value: float, sex: str, dentition: str) -> int:
    """根据特征名、性别和牙列期评估测量值等级"""
    sex = sex.lower()
    dentition = dentition.lower()

    # ANB的特殊处理（存储的是范围，不是均值±标准差）
    if feature == "ANB":
        tb = THRESHOLDS.get("ANB", {}).get(sex, {})
        rng = tb.get(dentition) or tb.get("all")
        if not rng:
            logger.warning(f"ANB阈值未找到: sex={sex}, dentition={dentition}")
            return 0  # 默认正常
        low, high = rng
        if value > high:
            return 1  # 骨性II类
        if value < low:
            return 2  # 骨性III类
        return 0  # 骨性I类

    # 其他指标（使用均值±标准差）
    entry = THRESHOLDS.get(feature)
    if not entry:
        logger.warning(f"阈值未定义: {feature}")
        # 这里应该返回一个特殊值，表示无法判断，而不是默认正常
        return -1  # 表示无法判断

    sex_entry = entry.get(sex)
    if not sex_entry:
        logger.warning(f"阈值未定义: {feature} for sex={sex}")
        return -1

    # 尝试获取指定牙列期的阈值
    mean_std = sex_entry.get(dentition)
    if not mean_std:
        # 如果找不到指定牙列期，尝试其他可用的
        available = list(sex_entry.keys())
        if available:
            # 使用第一个可用的牙列期作为备选
            mean_std = sex_entry[available[0]]
            logger.warning(f"使用备选牙列期: {feature} {dentition}→{available[0]}")
        else:
            logger.warning(f"无可用阈值: {feature} for sex={sex}")
            return 0

    mean, std = mean_std
    low = mean - std
    high = mean + std

    # 判断逻辑
    if value > high:
        return 1  # 过度/偏高
    if value < low:
        return 2  # 不足/偏低
    return 0  # 正常