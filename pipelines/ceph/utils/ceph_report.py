"""Cephalometric measurement helpers."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import numpy as np

logger = logging.getLogger(__name__)

KEYPOINT_MAP = {
    "P1": "S",      # Sella - 蝶鞍中心点
    "P2": "N",      # Nasion - 鼻根点
    "P3": "Or",     # Orbitale - 眶下点
    "P4": "Po",     # Porion - 耳点
    "P5": "A",      # Subspinale - A点（上颌骨前缘最凹点）
    "P6": "B",      # Supramentale - B点（下颌骨前缘最凹点）
    "P7": "Pog",    # Pogonion - 颏前点
    "P8": "Me",     # Menton - 颏下点
    "P9": "Gn",     # Gnathion - 颏顶点
    "P10": "Go",    # Gonion - 下颌角点
    "P11": "L1",    # Lower Incisor - 下切牙切缘
    "P12": "UI",    # Upper Incisor - 上切牙切缘
    "P13": "PNS",   # Posterior Nasal Spine - 后鼻棘
    "P14": "ANS",   # Anterior Nasal Spine - 前鼻棘
    "P15": "Ar",    # Articulare - 关节点
    "P16": "Co",    # Condylion - 髁突顶点
    "P17": "PTM",   # Pterygomaxillary - 翼上颌裂点
    "P18": "Pt",    # Point Pt
    "P19": "U1A",   # Upper Incisor Apex - 上切牙根尖
    "P20": "L1A",   # Lower Incisor Apex - 下切牙根尖
    "P21": "U6",    # Upper 6th tooth - 上颌第一磨牙
    "P22": "L6",    # Lower 6th tooth - 下颌第一磨牙
    "P23": "Ba",    # Basion - 颅底点
    "P24": "Bo",    # Bolton point - Bolton点
    "P25": "Pcd"    # Posterior Condylion - 髁突后点（关键：位于S点后方）
}

ANB_SKELETAL_II_THRESHOLD = 6.0
ANB_SKELETAL_III_THRESHOLD = 2.0
FH_MP_HIGH_ANGLE_THRESHOLD = 33.0
FH_MP_LOW_ANGLE_THRESHOLD = 25.0
SGO_NME_HORIZONTAL_THRESHOLD = 71.0
SGO_NME_VERTICAL_THRESHOLD = 63.0

# 默认像素间距常量（已废弃，仅保留用于向后兼容旧代码调用）
# 
# ⚠️ 重要：API 层（server/api.py）是唯一的默认值来源
# 所有通过 API 进入的请求都已保证 pixel_spacing 有值
# 如果此模块收到 None，说明调用方存在 bug，应该修复调用方而非在此处静默处理
#
# 此常量仅用于：
#   1. 向后兼容：旧的直接调用 calculate_measurements() 的代码
#   2. 单元测试：测试代码可能不经过 API 层
DEFAULT_SPACING_MM_PER_PIXEL = 0.1

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
    "U1_SN_Angle": {
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
        "female": {"mixed": (78.0, 4.0), "permanent": (84.0, 3.0)},  # 女性恒牙期: 84±3°
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
    "U1_PP_Upper_Anterior_Alveolar_Height": {  # U1-PP
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

def calculate_measurements(
    landmarks: Dict[str, np.ndarray], 
    sex: str = "male", 
    dentition: str = "permanent",
    spacing: float = DEFAULT_SPACING_MM_PER_PIXEL,
) -> Dict[str, Dict[str, Any]]:
    """
    Derive cephalometric measurements from landmark coordinates.
    
    Args:
        landmarks: 关键点坐标字典（像素坐标）
        sex: 性别 ("male" / "female")
        dentition: 牙列期 ("mixed" / "permanent")
        spacing: 像素间距 (mm/pixel)，默认 0.1 mm/pixel
        
    Returns:
        测量结果字典，长度单位为 mm
    """
    measurements: Dict[str, Dict[str, Any]] = {}

    sex = sex.lower()
    dentition = dentition.lower()
    if dentition not in ("mixed", "permanent", "all"):
        # 兜底：允许 'all' 用于 ANB male 全周期情况
        logger.warning(f"Invalid dentition '{dentition}', fallback to 'permanent'")
        dentition = "permanent"
    
    # 记录使用的参数（用于排查问题）
    logger.info(f"[计算参数] 性别: {sex}, 牙列期: {dentition}, spacing: {spacing} mm/pixel")

    # === 角度测量（不需要 spacing）===
    measurements["ANB_Angle"] = _compute_anb(landmarks, sex=sex, dentition=dentition)
    measurements["FH_MP_Angle"] = _compute_fh_mp(landmarks, sex=sex, dentition=dentition)
    measurements["SNA_Angle"] = _compute_sna(landmarks, sex=sex, dentition=dentition)
    measurements["SNB_Angle"] = _compute_snb(landmarks, sex=sex, dentition=dentition)
    measurements["IMPA_Angle"] = _compute_impa(landmarks, sex=sex, dentition=dentition)
    measurements["U1_NA_Angle"] = _compute_u1_na_angle(landmarks, sex=sex, dentition=dentition)
    measurements["FMIA_Angle"] = _compute_fmia(landmarks, sex=sex, dentition=dentition)
    measurements["L1_NB_Angle"] = _compute_l1_nb_angle(landmarks, sex=sex, dentition=dentition)
    measurements["U1_L1_Inter_Incisor_Angle"] = _compute_interincisor_angle(landmarks, sex=sex, dentition=dentition)
    measurements["Mandibular_Growth_Angle"] = _compute_face_axis(landmarks, sex=sex, dentition=dentition)
    measurements["U1_SN_Angle"] = _compute_u1_sn(landmarks, sex=sex, dentition=dentition)
    measurements["Y_Axis_Angle"] = _compute_y_axis_angle(landmarks, sex=sex, dentition=dentition)
    measurements["SN_MP_Angle"] = _compute_sn_mp_angle(landmarks, sex=sex, dentition=dentition)
    measurements["Mandibular_Growth_Type_Angle"] = _compute_mandibular_growth_type_angle(landmarks, sex=sex, dentition=dentition)
    
    # === 比率测量（不需要 spacing，分子分母抵消）===
    measurements["SGo_NMe_Ratio"] = _compute_sgo_nme(landmarks, sex=sex, dentition=dentition)

    # === 长度测量（需要 spacing 转换为 mm）===
    measurements["PtmANS_Length"] = _compute_ptmans_length(landmarks, sex=sex, dentition=dentition, spacing=spacing)
    measurements["GoPo_Length"] = _compute_gopo_length(landmarks, sex=sex, dentition=dentition, spacing=spacing)
    measurements["PoNB_Length"] = _compute_ponb_length(landmarks, sex=sex, dentition=dentition, spacing=spacing)
    measurements["Upper_Jaw_Position"] = _compute_ptm_s(landmarks, sex=sex, dentition=dentition, spacing=spacing)
    measurements["Pcd_Lower_Position"] = _compute_pcd_s(landmarks, sex=sex, dentition=dentition, spacing=spacing)
    measurements["Distance_Witsmm"] = _compute_wits(landmarks, sex=sex, dentition=dentition, spacing=spacing)
    measurements["U1_NA_Incisor_Length"] = _compute_u1_na_mm(landmarks, sex=sex, dentition=dentition, spacing=spacing)
    measurements["L1_NB_Distance"] = _compute_l1_nb_mm(landmarks, sex=sex, dentition=dentition, spacing=spacing)
    measurements["S_N_Anterior_Cranial_Base_Length"] = _compute_s_n_length(landmarks, sex=sex, dentition=dentition, spacing=spacing)
    measurements["Go_Me_Length"] = _compute_go_me_length(landmarks, sex=sex, dentition=dentition, spacing=spacing)
    measurements["U1_PP_Upper_Anterior_Alveolar_Height"] = _compute_u1_pp(landmarks, sex=sex, dentition=dentition, spacing=spacing)
    measurements["L1_MP_Lower_Anterior_Alveolar_Height"] = _compute_l1_mp_height(landmarks, sex=sex, dentition=dentition, spacing=spacing)
    measurements["U6_PP_Upper_Posterior_Alveolar_Height"] = _compute_u6_pp_height(landmarks, sex=sex, dentition=dentition, spacing=spacing)
    measurements["L6_MP_Lower_Posterior_Alveolar_Height"] = _compute_l6_mp_height(landmarks, sex=sex, dentition=dentition, spacing=spacing)

    # === 综合评估 ===
    measurements["Jaw_Development_Coordination"] = _compute_jaw_coordination(measurements)

    return measurements

def _compute_anb(landmarks: Dict[str, np.ndarray], sex: str = "male", dentition: str = "permanent") -> Dict[str, Any]:
    """
    计算 SNA、SNB 和 ANB 角度
    
    SNA: S-N-A 角，顶点在 N，测量上颌骨相对颅底的位置
    SNB: S-N-B 角，顶点在 N，测量下颌骨相对颅底的位置
    ANB: SNA - SNB，测量上下颌骨的相对位置关系
    
    注意：使用无向夹角计算（0°~180°），避免图像坐标系导致的负值问题
    """
    required = ["P1", "P2", "P5", "P6"]  # S, N, A, B
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)

    s, n, a, b = (landmarks[idx] for idx in required)
    
    # 从顶点 N 出发的两条射线向量
    v_ns = s - n  # N → S
    v_na = a - n  # N → A
    v_nb = b - n  # N → B
    
    # 使用无向夹角计算（始终返回正值 0°~180°）
    sna = _angle_between_vectors(v_ns, v_na)
    snb = _angle_between_vectors(v_ns, v_nb)
    
    # ANB = SNA - SNB
    # 正值表示 A 点相对更靠前（II类倾向），负值表示 B 点相对更靠前（III类倾向）
    anb = sna - snb

    conclusion_level = _get_skeletal_class(anb, sex=sex, dentition=dentition)

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


def _compute_ptmans_length(landmarks, sex: str = "male", dentition: str = "permanent", spacing: float = DEFAULT_SPACING_MM_PER_PIXEL):
    required = ["P17", "P14"]  # PTM-ANS
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    length_px = np.linalg.norm(landmarks["P17"] - landmarks["P14"])
    length_mm = length_px * spacing  # 像素转毫米

    level = _evaluate_by_threshold("PtmANS_Length", length_mm, sex, dentition)
    return {"value": float(length_mm), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_gopo_length(landmarks, sex: str = "male", dentition: str = "permanent", spacing: float = DEFAULT_SPACING_MM_PER_PIXEL):
    """第3项：Go-Po长度（Pog在下颌平面上的投影长度）—— 修复除零风险"""
    required = ["P10", "P7", "P8"]  # Go, Pog, Me
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    go, pog, me = landmarks["P10"], landmarks["P7"], landmarks["P8"]
    mp_vec = me - go

    # 关键修复：防止向量长度为0导致除零崩溃
    norm_mp = np.linalg.norm(mp_vec)
    if norm_mp < 1e-8:
        logger.warning("下颌平面向量退化，GoPo_Length 返回 0")
        return {"value": 0.0, "unit": "mm", "conclusion": 0, "status": "ok"}

    proj_scalar = np.dot(pog - go, mp_vec) / (norm_mp ** 2)
    length_px = abs(proj_scalar) * norm_mp
    length_mm = length_px * spacing  # 像素转毫米
    level = _evaluate_by_threshold("GoPo_Length", length_mm, sex, dentition)
    return {"value": float(length_mm), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_ponb_length(landmarks, sex: str = "male", dentition: str = "permanent", spacing: float = DEFAULT_SPACING_MM_PER_PIXEL):
    required = ["P7", "P2", "P6"]  # Pog 到 NB 的垂直距离
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    pog, n, b = landmarks["P7"], landmarks["P2"], landmarks["P6"]
    nb_vec = b - n
    dist_px = abs(np.cross(nb_vec, pog - n) / np.linalg.norm(nb_vec))
    dist_mm = dist_px * spacing  # 像素转毫米
    # PoNB 可能为正负，绝对值判断是否偏离正常均值
    level = _evaluate_by_threshold("PoNB_Length", float(dist_mm), sex, dentition)
    return {"value": float(dist_mm), "unit": "mm", "conclusion": level, "status": "ok"}

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

def _compute_ptm_s(landmarks, sex: str = "male", dentition: str = "permanent", spacing: float = DEFAULT_SPACING_MM_PER_PIXEL):
    required = ["P17", "P1"]
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    length_px = np.linalg.norm(landmarks["P17"] - landmarks["P1"])
    length_mm = length_px * spacing  # 像素转毫米
    level = _evaluate_by_threshold("Upper_Jaw_Position", length_mm, sex, dentition)
    return {"value": float(length_mm), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_pcd_s(landmarks, sex: str = "male", dentition: str = "permanent", spacing: float = DEFAULT_SPACING_MM_PER_PIXEL):
    """
    Pcd-S 距离：蝶鞍点到髁突后点的距离
    
    解剖说明：
    - S (Sella): 蝶鞍中心点，位于颅底中央
    - Pcd (Posterior Condylion): 髁突后点，下颌关节的后缘
    - Pcd 位于 S 点的后下方
    
    几何逻辑（反向指标）：
    - 距离增大 (>22mm) → 髁突过于靠后 → 下颌关节后移 → 下颌整体后缩 (Level=1)
    - 距离减小 (<16mm) → 髁突过于靠前 → 下颌关节前移 → 下颌整体前突 (Level=2)
    - 正常范围：16-22mm (男性恒牙期 19±3mm)
    """
    required = ["P25", "P1"]  # Pcd, S
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    length_px = np.linalg.norm(landmarks["P25"] - landmarks["P1"])
    length_mm = length_px * spacing  # 像素转毫米
    level = _evaluate_by_threshold("Pcd_Lower_Position", length_mm, sex, dentition)
    return {"value": float(length_mm), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_wits(landmarks, sex: str = "male", dentition: str = "permanent", spacing: float = DEFAULT_SPACING_MM_PER_PIXEL):
    """
    Wits 值：上下颌骨的位置关系
    将 A 点和 B 点垂直投影到参考平面（这里使用 FH 平面近似咬合平面）
    
    正值：A 点投影在 B 点投影的前方（II 类倾向）
    负值：B 点投影在 A 点投影的前方（III 类倾向）
    
    正常值约 -1.4±2.8mm
    """
    required = ["P5", "P6", "P3", "P4"]  # A, B, Or, Po
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    a, b, or_pt, po = (landmarks[k] for k in required)
    
    # FH 平面向量（从 Po 指向 Or，向前方向）
    fh = or_pt - po
    fh_norm_sq = np.dot(fh, fh)
    if fh_norm_sq < 1e-8:
        return {"value": 0.0, "unit": "mm", "conclusion": 0, "status": "ok"}
    
    # A、B 点在 FH 平面上的投影参数
    # 以 Po 为参考原点
    a_proj = np.dot(a - po, fh) / fh_norm_sq
    b_proj = np.dot(b - po, fh) / fh_norm_sq
    
    # Wits = A投影位置 - B投影位置
    # 正值：A 更靠前（II 类）；负值：B 更靠前（III 类）
    wits_px = (a_proj - b_proj) * np.linalg.norm(fh)
    wits_mm = wits_px * spacing
    
    level = _evaluate_by_threshold("Distance_Witsmm", wits_mm, sex, dentition)
    return {"value": float(wits_mm), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_u1_sn(landmarks, sex: str = "male", dentition: str = "permanent"):
    """
    U1-SN 角：上中切牙长轴与 SN 平面的下内角
    正常值约 107±6°
    
    牙轴方向：从根尖指向切端（向下向前）
    SN 方向：从 S 指向 N（向前）
    """
    required = ["P12", "P19", "P1", "P2"]  # UI(切端), U1A(根尖), S, N
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    u1, u1a, s, n = (landmarks[k] for k in required)
    
    # 牙轴向量：从根尖指向切端
    axis = u1 - u1a
    # SN 平面向量：从 S 指向 N
    sn = n - s
    
    # 计算夹角
    angle = _angle_between_vectors(axis, sn)
    
    # U1-SN 测量的是下内角，如果计算出的是上外角（锐角），需要取补角
    # 正常 U1-SN 约 107°，是钝角
    if angle < 90:
        angle = 180 - angle
    
    level = _evaluate_by_threshold("U1_SN_Angle", angle, sex, dentition)
    
    # 调试日志：记录 U1_SN_Angle 计算结果（用于排查标红问题）
    logger.info(f"[U1_SN_Angle] 角度: {angle:.2f}°, Level: {level}, 性别: {sex}, 牙期: {dentition}")
    
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_impa(landmarks, sex: str = "male", dentition: str = "permanent"):
    """
    IMPA (L1-MP)：下中切牙长轴与下颌平面(MP)的上内角
    正常值约 93±7°
    
    牙轴方向：从根尖指向切端
    MP 方向：从 Go 指向 Me
    """
    required = ["P11", "P20", "P8", "P10"]  # L1(切端), L1A(根尖), Me, Go
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    l1, l1a, me, go = (landmarks[k] for k in required)
    
    # 牙轴向量：从根尖指向切端
    axis = l1 - l1a
    # 下颌平面向量：从 Go 指向 Me
    mp = me - go
    
    # 计算夹角
    angle = _angle_between_vectors(axis, mp)
    
    # IMPA 测量的是上内角，正常约 93°
    # 如果计算出的是锐角（外角），需要取补角
    if angle < 90:
        angle = 180 - angle
    
    level = _evaluate_by_threshold("IMPA_Angle", angle, sex, dentition)
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_u1_pp(landmarks, sex: str = "male", dentition: str = "permanent", spacing: float = DEFAULT_SPACING_MM_PER_PIXEL):
    required = ["P12", "P14", "P13"]
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    u1, ans, pns = (landmarks[k] for k in required)
    pp = pns - ans

    dist_px = _safe_cross_distance(pp, u1, ans)
    dist_mm = dist_px * spacing  # 像素转毫米
    level = _evaluate_by_threshold("U1_PP_Upper_Anterior_Alveolar_Height", dist_mm, sex, dentition)
    return {"value": float(dist_mm), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_u1_na_angle(landmarks, sex: str = "male", dentition: str = "permanent"):
    """
    U1-NA 角：上切牙长轴与 NA 线的夹角
    正常值约 22±6°，是锐角
    
    牙轴方向：从根尖指向切端
    NA 方向：从 N 指向 A
    """
    required = ["P12", "P19", "P2", "P5"]  # UI(切端), U1A(根尖), N, A
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    u1, u1a, n, a = (landmarks[k] for k in required)
    
    # 牙轴向量：从根尖指向切端
    axis = u1 - u1a
    # NA 线向量：从 N 指向 A
    na = a - n
    
    # 计算夹角
    angle = _angle_between_vectors(axis, na)
    
    # U1-NA 角正常约 22°，是锐角；如果计算出钝角，需要取补角
    if angle > 90:
        angle = 180 - angle
    
    level = _evaluate_by_threshold("U1_NA_Angle", angle, sex, dentition)
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_u1_na_mm(landmarks, sex: str = "male", dentition: str = "permanent", spacing: float = DEFAULT_SPACING_MM_PER_PIXEL):
    required = ["P12", "P2", "P5"]
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    u1, n, a = landmarks["P12"], landmarks["P2"], landmarks["P5"]
    na = a - n
    dist_px = abs(np.cross(na, u1 - n) / np.linalg.norm(na))
    dist_mm = dist_px * spacing  # 像素转毫米
    level = _evaluate_by_threshold("U1_NA_Incisor_Length", dist_mm, sex, dentition)
    return {"value": float(dist_mm), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_fmia(landmarks, sex: str = "male", dentition: str = "permanent"):
    """
    FMIA (L1-FH)：下中切牙长轴与 FH 平面的夹角
    正常值约 54±6°，是锐角
    
    牙轴方向：从根尖指向切端
    FH 方向：从 Po 指向 Or（向前）
    """
    required = ["P11", "P20", "P3", "P4"]  # L1(切端), L1A(根尖), Or, Po
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    l1, l1a, or_pt, po = (landmarks[k] for k in required)
    
    # 牙轴向量：从根尖指向切端
    axis = l1 - l1a
    # FH 平面向量：从 Po 指向 Or
    fh = or_pt - po
    
    # 计算夹角
    angle = _angle_between_vectors(axis, fh)
    
    # FMIA 正常约 54°，是锐角；如果计算出钝角，取补角
    if angle > 90:
        angle = 180 - angle
    
    level = _evaluate_by_threshold("FMIA_Angle", angle, sex, dentition)
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_l1_nb_angle(landmarks, sex: str = "male", dentition: str = "permanent"):
    """
    L1-NB 角：下中切牙长轴与 NB 线的夹角
    正常值约 30±6°，是锐角
    
    牙轴方向：从根尖指向切端
    NB 方向：从 N 指向 B
    """
    required = ["P11", "P20", "P2", "P6"]  # L1(切端), L1A(根尖), N, B
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    l1, l1a, n, b = (landmarks[k] for k in required)
    
    # 牙轴向量：从根尖指向切端
    axis = l1 - l1a
    # NB 线向量：从 N 指向 B
    nb = b - n
    
    # 计算夹角
    angle = _angle_between_vectors(axis, nb)
    
    # L1-NB 角正常约 30°，是锐角；如果计算出钝角，取补角
    if angle > 90:
        angle = 180 - angle
    
    level = _evaluate_by_threshold("L1_NB_Angle", angle, sex, dentition)
    return {"value": float(angle), "unit": "degrees", "conclusion": level, "status": "ok"}

def _compute_l1_nb_mm(landmarks, sex: str = "male", dentition: str = "permanent", spacing: float = DEFAULT_SPACING_MM_PER_PIXEL):
    required = ["P11", "P2", "P6"]
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    l1, n, b = landmarks["P11"], landmarks["P2"], landmarks["P6"]
    nb = b - n

    dist_px = abs(np.cross(nb, l1 - n) / np.linalg.norm(nb))
    dist_mm = dist_px * spacing  # 像素转毫米
    level = _evaluate_by_threshold("L1_NB_Distance", dist_mm, sex, dentition)
    return {"value": float(dist_mm), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_interincisor_angle(landmarks, sex: str = "male", dentition: str = "permanent"):
    """
    U1-L1 角（上下切牙角）：上下中切牙长轴之间的夹角
    正常值约 121±9°，是钝角
    
    上切牙轴：从根尖指向切端（向下向前）
    下切牙轴：从根尖指向切端（向上向前）
    """
    required = ["P12", "P19", "P11", "P20"]  # UI, U1A, L1, L1A
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    
    # 上切牙轴：从根尖(U1A)指向切端(UI)
    u_axis = landmarks["P12"] - landmarks["P19"]
    # 下切牙轴：从根尖(L1A)指向切端(L1)
    l_axis = landmarks["P11"] - landmarks["P20"]
    
    # 计算夹角（两牙轴的夹角）
    angle = _angle_between_vectors(u_axis, l_axis)
    
    # 上下切牙角正常约 121°~127°，是钝角
    # 如果计算出锐角，取补角
    if angle < 90:
        angle = 180 - angle
    
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

def _compute_s_n_length(landmarks, sex: str = "male", dentition: str = "permanent", spacing: float = DEFAULT_SPACING_MM_PER_PIXEL):
    required = ["P1", "P2"]
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    length_px = np.linalg.norm(landmarks["P1"] - landmarks["P2"])
    length_mm = length_px * spacing  # 像素转毫米
    level = _evaluate_by_threshold("S_N_Anterior_Cranial_Base_Length", length_mm, sex, dentition)
    return {"value": float(length_mm), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_go_me_length(landmarks, sex: str = "male", dentition: str = "permanent", spacing: float = DEFAULT_SPACING_MM_PER_PIXEL):
    required = ["P10", "P8"]
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    length_px = np.linalg.norm(landmarks["P10"] - landmarks["P8"])
    length_mm = length_px * spacing  # 像素转毫米
    level = _evaluate_by_threshold("Go_Me_Length", length_mm, sex, dentition)
    return {"value": float(length_mm), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_jaw_coordination(measurements):
    upper = measurements.get("SNA_Angle", {}).get("conclusion", 0)
    if upper == 0:
        upper = measurements.get("PtmANS_Length", {}).get("conclusion", 0)
    lower = measurements.get("SNB_Angle", {}).get("conclusion", 0)
    return {"value": [upper, lower], "unit": "multi", "conclusion": [upper, lower], "status": "ok"}


def _compute_sn_fh_angle(landmarks):
    """
    SN-FH 角：前颅底平面（SN）与眶耳平面（FH）的夹角
    正常值约 7°~10°（很少超过 15°）
    
    SN 平面：从 S 指向 N（向前）
    FH 平面：从 Po 指向 Or（向前）
    
    两个平面几乎平行，夹角很小
    """
    required = ["P1", "P2", "P3", "P4"]  # S, N, Or, Po
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)
    S, N, Or, Po = (landmarks[k] for k in required)
    
    # SN 向量：从 S 指向 N（向前）
    sn_vec = N - S
    # FH 向量：从 Po 指向 Or（向前）—— 修正方向！
    fh_vec = Or - Po
    
    # 计算夹角
    angle = _angle_between_vectors(sn_vec, fh_vec)
    
    # 取锐角（正常情况下应该是 7-10°，不应超过 90°）
    if angle > 90:
        angle = 180 - angle
    
    # 判断等级：正常约 7±2°
    if angle > 9.0:
        level = 1  # 偏大
    elif angle < 5.0:
        level = 2  # 偏小
    else:
        level = 0  # 正常
    
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


def _compute_l1_mp_height(landmarks, sex: str = "male", dentition: str = "permanent", spacing: float = DEFAULT_SPACING_MM_PER_PIXEL):
    """第33项：下前牙槽高度 L1切缘到下颌平面（Go-Me）的垂直距离"""
    required = ["P11", "P10", "P8"]  # L1, Go, Me
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    l1, go, me = landmarks["P11"], landmarks["P10"], landmarks["P8"]
    mp_vec = me - go
    dist_px = _safe_cross_distance(mp_vec, l1, go)
    dist_mm = dist_px * spacing  # 像素转毫米
    level = _evaluate_by_threshold("L1_MP_Lower_Anterior_Alveolar_Height", dist_mm, sex, dentition)
    return {"value": float(dist_mm), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_u6_pp_height(landmarks, sex: str = "male", dentition: str = "permanent", spacing: float = DEFAULT_SPACING_MM_PER_PIXEL):
    """第34项：上后牙槽高度 U6到腭平面（ANS-PNS）的垂直距离"""
    required = ["P21", "P14", "P13"]  # U6, ANS, PNS
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    u6, ans, pns = landmarks["P21"], landmarks["P14"], landmarks["P13"]
    pp_vec = pns - ans
    dist_px = _safe_cross_distance(pp_vec, u6, ans)
    dist_mm = dist_px * spacing  # 像素转毫米
    level = _evaluate_by_threshold("U6_PP_Upper_Posterior_Alveolar_Height", dist_mm, sex, dentition)
    return {"value": float(dist_mm), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_l6_mp_height(landmarks, sex: str = "male", dentition: str = "permanent", spacing: float = DEFAULT_SPACING_MM_PER_PIXEL):
    """第35项：下后牙槽高度 L6到下颌平面（Go-Me）的垂直距离"""
    required = ["P22", "P10", "P8"]  # L6, Go, Me
    if not _has_points(landmarks, required):
        return _missing_measurement("mm", required, landmarks)
    l6, go, me = landmarks["P22"], landmarks["P10"], landmarks["P8"]
    mp_vec = me - go
    dist_px = _safe_cross_distance(mp_vec, l6, go)
    dist_mm = dist_px * spacing  # 像素转毫米
    level = _evaluate_by_threshold("L6_MP_Lower_Posterior_Alveolar_Height", dist_mm, sex, dentition)
    return {"value": float(dist_mm), "unit": "mm", "conclusion": level, "status": "ok"}

def _compute_mandibular_growth_type_angle(landmarks, sex: str = "male", dentition: str = "permanent"):
    """
    Mandibular_Growth_Type_Angle（Björk Sum）
    = 鞍角(N-S-Ar) + 关节角(S-Ar-Go) + 下颌角(Ar-Go-Me)
    正常范围：390.0–402.0°
    
    修复说明：
    - Bjork Sum 的标准定义只包含 3 个角度，不包含下颌平面角（SN-MP）
    - 之前错误地加入了 angle4，导致计算结果偏大或偏小
    - 正确公式见: Björk A. (1969). Prediction of mandibular growth rotation.
    """
    required = ["P1", "P2", "P15", "P10", "P8"]  # S, N, Ar, Go, Me
    if not _has_points(landmarks, required):
        return _missing_measurement("degrees", required, landmarks)

    S  = landmarks["P1"]
    N  = landmarks["P2"]
    Ar = landmarks["P15"]
    Go = landmarks["P10"]
    Me = landmarks["P8"]

    # 1. 鞍角 Saddle angle ∠N-S-Ar (顶点在S)
    #    从 S→N 和 S→Ar 两条射线的夹角
    angle1 = _angle_between_vectors(N - S, Ar - S)

    # 2. 关节角 Articular angle ∠S-Ar-Go (顶点在Ar)
    #    从 Ar→S 和 Ar→Go 两条射线的夹角
    angle2 = _angle_between_vectors(S - Ar, Go - Ar)

    # 3. 下颌角 Gonial angle ∠Ar-Go-Me (顶点在Go)
    #    从 Go→Ar 和 Go→Me 两条射线的夹角
    angle3 = _angle_between_vectors(Ar - Go, Me - Go)

    # Bjork Sum = 只包含这 3 个角度（已修复：移除了 angle4）
    total = angle1 + angle2 + angle3

    # Level 判断
    level = _evaluate_by_threshold("Mandibular_Growth_Type_Angle", total, sex, dentition)

    return {
        "value": float(total),
        "unit": "degrees",
        "details": {
            "Saddle_angle_N_S_Ar": float(angle1),
            "Articular_angle_S_Ar_Go": float(angle2),
            "Gonial_angle_Ar_Go_Me": float(angle3),
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

    # 判断逻辑（增加浮点数容差，避免边界值误判）
    epsilon = 0.01  # 容差
    if value > high + epsilon:
        return 1  # 过度/偏高
    if value < low - epsilon:
        return 2  # 不足/偏低
    return 0  # 正常
def _is_valid_point(point: Any) -> bool:
    """判断一个点坐标是否有效（2维、非NaN）"""
    if point is None:
        return False
    try:
        arr = np.asarray(point, dtype=float)
        return arr.shape == (2,) and not np.isnan(arr).any()
    except:
        return False

def _safe_cross_distance(vec_line: np.ndarray, point: np.ndarray, ref_point: np.ndarray) -> float:
    """
    安全计算点到直线的垂直距离（史上最稳版本）
    彻底解决 np.cross 返回标量导致 [0] 索引崩溃的问题
    """
    if not (_is_valid_point(vec_line) and _is_valid_point(point) and _is_valid_point(ref_point)):
        return 0.0

    a = vec_line
    b = point - ref_point
    cross_val = np.cross(a, b)

    # 关键防御：兼容标量、1维数组、2维数组
    if np.isscalar(cross_val):
        cross_abs = abs(float(cross_val))
    elif cross_val.size == 0:
        cross_abs = 0.0
    else:
        cross_abs = abs(float(cross_val.item()))

    norm = np.linalg.norm(a)
    return cross_abs / norm if norm > 1e-8 else 0.0