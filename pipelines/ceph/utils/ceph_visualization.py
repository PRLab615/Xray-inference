"""可视化构建：为测量项生成线段与虚拟点指令。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from .ceph_report import KEYPOINT_MAP, KEYPOINT_MAP_11

# 反向映射：短标签 -> 点位编号（P1...）
_SHORT_KEY_TO_POINT_ID = {short: pid for pid, short in KEYPOINT_MAP.items()}


def build_visualization_map(
    measurements: Dict[str, Dict[str, Any]],
    landmarks_block: Dict[str, Any],
    landmarks_11_block: Optional[Dict[str, Any]] = None,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    为所有测量项生成可视化指令。
    返回 dict[name] = VisualizationPayload | None
    """
    coords25 = _extract_coordinates(landmarks_block)
    coords11 = _extract_coordinates(landmarks_11_block) if landmarks_11_block else {}
    if not coords25 and not coords11:
        return {name: None for name in measurements}

    landmarks = _normalize_landmarks_all(coords25, coords11)
    viz_map: Dict[str, Optional[Dict[str, Any]]] = {}

    for name, payload in measurements.items():
        viz_map[name] = build_single(name, payload, landmarks)

    return viz_map


def build_single(
    name: str,
    payload: Dict[str, Any],
    landmarks: Dict[str, np.ndarray],
) -> Optional[Dict[str, Any]]:
    """针对单个测量项生成 VisualizationPayload。"""
    if not payload or payload.get("status") != "ok":
        return None

    if name == "Reference_Planes":
        return _reference_planes_payload(landmarks)
    if name == "ANB_Angle":
        return _anb_payload(landmarks)
    if name == "SNA_Angle":
        return _sna_payload(landmarks)
    if name == "SNB_Angle":
        return _snb_payload(landmarks)
    if name == "PoNB_Length":
        return _ponb_payload(landmarks)
    if name == "GoPo_Length":
        return _gopo_payload(landmarks)
    if name == "Distance_Witsmm":
        return _wits_payload(landmarks)
    if name == "FH_MP_Angle":
        return _fh_mp_payload(landmarks)
    if name == "U1_SN_Angle":
        return _u1_sn_payload(landmarks)
    if name == "IMPA_Angle":
        return _impa_payload(landmarks)
    if name == "Jaw_Development_Coordination":
        return _jaw_coordination_payload(landmarks)
    if name == "SGo_NMe_Ratio":
        return _sgo_nme_payload(landmarks)
    if name == "PtmANS_Length":
        return _ptm_ans_payload(landmarks)
    if name == "Upper_Jaw_Position":
        return _ptm_s_payload(landmarks)
    if name == "Pcd_Lower_Position":
        return _pcd_s_payload(landmarks)
    if name == "U1_NA_Angle":
        return _u1_na_angle_payload(landmarks)
    if name == "U1_NA_Incisor_Length":
        return _u1_na_length_payload(landmarks)
    if name == "FMIA_Angle":
        return _fmia_payload(landmarks)
    if name == "L1_NB_Angle":
        return _l1_nb_angle_payload(landmarks)
    if name == "L1_NB_Distance":
        return _l1_nb_distance_payload(landmarks)
    if name == "U1_L1_Inter_Incisor_Angle":
        return _u1_l1_angle_payload(landmarks)
    if name == "Y_Axis_Angle":
        return _y_axis_payload(landmarks)
    if name == "Mandibular_Growth_Angle":
        return _mandibular_growth_payload(landmarks)
    if name == "SN_MP_Angle":
        return _sn_mp_payload(landmarks)
    if name == "U1_PP_Upper_Anterior_Alveolar_Height":
        return _u1_pp_payload(landmarks)
    if name == "L1_MP_Lower_Anterior_Alveolar_Height":
        return _l1_mp_height_payload(landmarks)
    if name == "U6_PP_Upper_Posterior_Alveolar_Height":
        return _u6_pp_payload(landmarks)
    if name == "L6_MP_Lower_Posterior_Alveolar_Height":
        return _l6_mp_payload(landmarks)
    if name == "Mandibular_Growth_Type_Angle":
        return _mandibular_growth_type_payload(landmarks)
    if name == "S_N_Anterior_Cranial_Base_Length":
        return _sn_length_payload(landmarks)
    if name == "Go_Me_Length":
        return _go_me_payload(landmarks)
    if name == "Airway_Gap":
        return _airway_gap_payload(landmarks)
    if name == "Adenoid_Index":
        return _adenoid_payload(landmarks)

    return None


def _reference_planes_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """绘制四条参考平面（纯参考线）。

    - SN: S↔N
    - FH: Po↔Or
    - PP: ANS↔PNS
    - MP: Go↔Me

    统一使用 Solid + Reference。
    """
    required = ["S", "N", "Po", "Or", "ANS", "PNS", "Go", "Me"]
    if not _has_points(landmarks, required):
        return None

    elements = [
        _line("S", "N", "Solid", "Reference"),
        _line("Po", "Or", "Solid", "Reference"),
        _line("ANS", "PNS", "Solid", "Reference"),
        _line("Go", "Me", "Solid", "Reference"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _sna_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["S", "N", "A"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("S", "N", "Solid", "Reference"),
        _line("N", "A", "Solid", "Measurement"),
        _angle("N", "S", "A", role="Measurement"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _snb_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["S", "N", "B"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("S", "N", "Solid", "Reference"),
        _line("N", "B", "Solid", "Measurement"),
        _angle("N", "S", "B", role="Measurement"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _anb_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """ANB：仅保留 N-A 与 N-B，并增加角度圆弧（Angle）。"""
    required = ["N", "A", "B"]
    if not _has_points(landmarks, required):
        return None

    elements = [
        _line("N", "A", "Solid", "Measurement"),
        _line("N", "B", "Solid", "Measurement"),
        _angle("N", "A", "B", role="Measurement"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _ponb_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["Pog", "N", "B"]
    if not _has_points(landmarks, required):
        return None
    pog, n, b = (landmarks[k] for k in required)
    foot = _project_point_onto_line(pog, n, b)
    foot_fmt = _format_point(foot)
    if foot_fmt is None:
        return None

    virtual_points = {"v_pog_on_nb": foot_fmt}
    elements = [
        _line("N", "B", "Solid", "Reference"),
        _line("Pog", "v_pog_on_nb", "Dashed", "Measurement"),
    ]
    return {"VirtualPoints": virtual_points, "Elements": elements}


def _gopo_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["Go", "Pog", "Me"]
    if not _has_points(landmarks, required):
        return None
    go, pog, me = (landmarks[k] for k in required)
    foot = _project_point_onto_line(pog, go, me)
    foot_fmt = _format_point(foot)
    if foot_fmt is None:
        return None

    virtual_points = {"v_pog_on_mp": foot_fmt}
    elements = [
        _line("Go", "Me", "Solid", "Reference"),
        _line("Pog", "v_pog_on_mp", "Dashed", "Measurement"),
    ]
    return {"VirtualPoints": virtual_points, "Elements": elements}


def _wits_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """
    Wits 值可视化（Bisected Occlusal Plane 版）
    - 使用后牙中点 (U6/L6) 和 前牙中点 (UI/L1) 定义 BOP
    - 绘制 BOP 连线、A/B 垂线、A0-B0 测量段
    """
    required = ["A", "B", "U6", "L6", "UI", "L1"]
    if not _has_points(landmarks, required):
        return None

    a = landmarks["A"]
    b = landmarks["B"]
    u6 = landmarks["U6"]
    l6 = landmarks["L6"]
    ui = landmarks["UI"]
    l1 = landmarks["L1"]

    # 计算中点（虚拟点）
    molar_mid = (u6 + l6) / 2.0
    incisal_mid = (ui + l1) / 2.0

    molar_mid_fmt = _format_point(molar_mid)
    incisal_mid_fmt = _format_point(incisal_mid)
    if molar_mid_fmt is None or incisal_mid_fmt is None:
        return None

    # A、B 向 BOP 的垂足
    foot_a = _project_point_onto_line(a, molar_mid, incisal_mid)
    foot_b = _project_point_onto_line(b, molar_mid, incisal_mid)

    foot_a_fmt = _format_point(foot_a)
    foot_b_fmt = _format_point(foot_b)
    if foot_a_fmt is None or foot_b_fmt is None:
        return None

    virtual_points = {
        "v_molar_mid": molar_mid_fmt,      # 后牙中点
        "v_incisal_mid": incisal_mid_fmt,  # 前牙中点
        "v_a_on_bop": foot_a_fmt,
        "v_b_on_bop": foot_b_fmt,
    }

    elements = [
        # BOP 平面参考线（虚线，从后到前）
        _line("v_molar_mid", "v_incisal_mid", "Dashed", "Reference"),
        # A、B 到 BOP 的垂线
        _line("A", "v_a_on_bop", "Dashed", "Measurement"),
        _line("B", "v_b_on_bop", "Dashed", "Measurement"),
        # Wits 测量段
        _line("v_a_on_bop", "v_b_on_bop", "Solid", "Measurement"),
    ]

    return {"VirtualPoints": virtual_points, "Elements": elements}


def _fh_mp_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """FH_MP_Angle: 计算 FH(Po-Or) 与 MP(Go-Me) 延长线交点，并补充角度。"""
    required = ["Po", "Or", "Go", "Me"]
    if not _has_points(landmarks, required):
        return None

    po, or_pt, go, me = (landmarks[k] for k in required)
    v_int = _get_intersection_point(po, or_pt, go, me)
    v_int_fmt = _format_point(v_int) if v_int is not None else None

    elements = [
        _line("Po", "Or", "Dashed", "Reference"),
        _line("Go", "Me", "Solid", "Reference"),
    ]

    if v_int_fmt:
        virtual_points = {"v_int": v_int_fmt}
        elements.extend([
            _line("Or", "v_int", "Dashed", "Reference"),
            _line("Go", "v_int", "Dashed", "Reference"),
            _angle("v_int", "Or", "Go", role="Measurement"),
        ])
        return {"VirtualPoints": virtual_points, "Elements": elements}

    return {"VirtualPoints": None, "Elements": elements}


def _u1_sn_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """U1_SN_Angle：计算 SN 与 U1-U1A 延长线交点，并补充延长线段 + 角度圆弧。"""
    required = ["S", "N", "UI", "U1A"]
    if not _has_points(landmarks, required):
        return None

    s, n, ui, u1a = (landmarks[k] for k in required)
    v_int = _get_intersection_point(s, n, ui, u1a)
    v_int_fmt = _format_point(v_int) if v_int is not None else None

    elements = [
        _line("S", "N", "Solid", "Reference"),
        _line("UI", "U1A", "Solid", "Measurement"),
    ]

    if v_int_fmt is not None:
        virtual_points = {"v_int": v_int_fmt}
        # 延长线（用端点到交点的虚线表示）
        elements.extend([
            _line("N", "v_int", "Dashed", "Reference"),
            _line("U1A", "v_int", "Dashed", "Reference"),
            _angle("v_int", "N", "U1A", role="Measurement"),
        ])
        return {"VirtualPoints": virtual_points, "Elements": elements}

    return {"VirtualPoints": None, "Elements": elements}


def _impa_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """IMPA_Angle：计算 MP(Go-Me) 与 L1-L1A 延长线交点，并补充延长线段 + 角度圆弧。"""
    required = ["Go", "Me", "L1", "L1A"]
    if not _has_points(landmarks, required):
        return None

    go, me, l1, l1a = (landmarks[k] for k in required)
    v_int = _get_intersection_point(go, me, l1, l1a)
    v_int_fmt = _format_point(v_int) if v_int is not None else None

    elements = [
        _line("Go", "Me", "Solid", "Reference"),
        _line("L1", "L1A", "Solid", "Measurement"),
    ]

    if v_int_fmt is not None:
        virtual_points = {"v_int": v_int_fmt}
        elements.extend([
            _line("Me", "v_int", "Dashed", "Reference"),
            _line("L1A", "v_int", "Dashed", "Reference"),
            _angle("v_int", "Me", "L1A", role="Measurement"),
        ])
        return {"VirtualPoints": virtual_points, "Elements": elements}

    return {"VirtualPoints": None, "Elements": elements}


def _jaw_coordination_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["N", "A", "B"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("N", "A", "Solid", "Measurement"),
        _line("N", "B", "Solid", "Measurement"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _sgo_nme_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["S", "Go", "N", "Me"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("S", "Go", "Solid", "Measurement"),
        _line("N", "Me", "Solid", "Measurement"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _ptm_ans_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """PtmANS_Length：PTM/ANS 在 FH(Po-Or)上的投影距离，并画出两条垂线。"""
    required = ["PTM", "ANS", "Po", "Or"]
    if not _has_points(landmarks, required):
        return None

    ptm, ans, po, or_pt = (landmarks[k] for k in required)

    v_ptm = _project_point_onto_line(ptm, po, or_pt)
    v_ans = _project_point_onto_line(ans, po, or_pt)
    v_ptm_fmt = _format_point(v_ptm)
    v_ans_fmt = _format_point(v_ans)
    if v_ptm_fmt is None or v_ans_fmt is None:
        return None

    virtual_points = {"v_ptm_on_fh": v_ptm_fmt, "v_ans_on_fh": v_ans_fmt}
    elements = [
        _line("PTM", "v_ptm_on_fh", "Dashed", "Reference"),
        _line("ANS", "v_ans_on_fh", "Dashed", "Reference"),
        _line("v_ptm_on_fh", "v_ans_on_fh", "Solid", "Measurement"),
    ]
    return {"VirtualPoints": virtual_points, "Elements": elements}


def _ptm_s_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """Upper_Jaw_Position：S/PTM 在 FH(Po-Or)上的投影距离，并画出两条垂线。"""
    required = ["S", "PTM", "Po", "Or"]
    if not _has_points(landmarks, required):
        return None

    s, ptm, po, or_pt = (landmarks[k] for k in required)

    v_s = _project_point_onto_line(s, po, or_pt)
    v_ptm = _project_point_onto_line(ptm, po, or_pt)
    v_s_fmt = _format_point(v_s)
    v_ptm_fmt = _format_point(v_ptm)
    if v_s_fmt is None or v_ptm_fmt is None:
        return None

    virtual_points = {"v_s_on_fh": v_s_fmt, "v_ptm_on_fh": v_ptm_fmt}
    elements = [
        _line("S", "v_s_on_fh", "Dashed", "Reference"),
        _line("PTM", "v_ptm_on_fh", "Dashed", "Reference"),
        _line("v_s_on_fh", "v_ptm_on_fh", "Solid", "Measurement"),
    ]
    return {"VirtualPoints": virtual_points, "Elements": elements}


def _pcd_s_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """Pcd_Lower_Position：S/Pcd 在 FH(Po-Or)上的投影距离，并画出两条垂线。"""
    required = ["S", "Pcd", "Po", "Or"]
    if not _has_points(landmarks, required):
        return None

    s, pcd, po, or_pt = (landmarks[k] for k in required)

    v_s = _project_point_onto_line(s, po, or_pt)
    v_pcd = _project_point_onto_line(pcd, po, or_pt)
    v_s_fmt = _format_point(v_s)
    v_pcd_fmt = _format_point(v_pcd)
    if v_s_fmt is None or v_pcd_fmt is None:
        return None

    virtual_points = {"v_s_on_fh": v_s_fmt, "v_pcd_on_fh": v_pcd_fmt}
    elements = [
        _line("S", "v_s_on_fh", "Dashed", "Reference"),
        _line("Pcd", "v_pcd_on_fh", "Dashed", "Reference"),
        _line("v_s_on_fh", "v_pcd_on_fh", "Solid", "Measurement"),
    ]
    return {"VirtualPoints": virtual_points, "Elements": elements}


def _u1_na_angle_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """U1_NA_Angle：计算 NA 与 U1-U1A 延长线交点，并补充延长线段 + 角度圆弧。"""
    required = ["N", "A", "UI", "U1A"]
    if not _has_points(landmarks, required):
        return None

    n, a, ui, u1a = (landmarks[k] for k in required)
    v_int = _get_intersection_point(n, a, ui, u1a)
    v_int_fmt = _format_point(v_int) if v_int is not None else None

    elements = [
        _line("N", "A", "Solid", "Reference"),
        _line("UI", "U1A", "Solid", "Measurement"),
    ]

    if v_int_fmt is not None:
        virtual_points = {"v_int": v_int_fmt}
        elements.extend([
            _line("A", "v_int", "Dashed", "Reference"),
            _line("U1A", "v_int", "Dashed", "Reference"),
            _angle("v_int", "A", "U1A", role="Measurement"),
        ])
        return {"VirtualPoints": virtual_points, "Elements": elements}

    return {"VirtualPoints": None, "Elements": elements}


def _u1_na_length_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["UI", "N", "A"]
    if not _has_points(landmarks, required):
        return None
    u1, n, a = (landmarks[k] for k in required)
    foot = _project_point_onto_line(u1, n, a)
    foot_fmt = _format_point(foot)
    if foot_fmt is None:
        return None
    virtual_points = {"v_u1_on_na": foot_fmt}
    elements = [
        _line("N", "A", "Solid", "Reference"),
        _line("UI", "v_u1_on_na", "Dashed", "Measurement"),
    ]
    return {"VirtualPoints": virtual_points, "Elements": elements}


def _fmia_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """FMIA_Angle：计算 FH(Po-Or) 与 L1-L1A 延长线交点，并补充延长线段 + 角度圆弧。"""
    required = ["L1", "L1A", "Po", "Or"]
    if not _has_points(landmarks, required):
        return None

    l1, l1a, po, or_pt = (landmarks[k] for k in required)
    v_int = _get_intersection_point(po, or_pt, l1, l1a)
    v_int_fmt = _format_point(v_int) if v_int is not None else None

    elements = [
        _line("Po", "Or", "Dashed", "Reference"),
        _line("L1", "L1A", "Solid", "Measurement"),
    ]

    if v_int_fmt is not None:
        virtual_points = {"v_int": v_int_fmt}
        elements.extend([
            _line("Or", "v_int", "Dashed", "Reference"),
            _line("L1A", "v_int", "Dashed", "Reference"),
            _angle("v_int", "Or", "L1A", role="Measurement"),
        ])
        return {"VirtualPoints": virtual_points, "Elements": elements}

    return {"VirtualPoints": None, "Elements": elements}


def _l1_nb_angle_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """L1_NB_Angle：在 NB 与 L1 轴的夹角处增加角度圆弧。"""
    required = ["N", "B", "L1", "L1A"]
    if not _has_points(landmarks, required):
        return None

    n, b, l1, l1a = (landmarks[k] for k in required)
    v_int = _get_intersection_point(n, b, l1, l1a)
    v_int_fmt = _format_point(v_int) if v_int is not None else None

    elements = [
        _line("N", "B", "Solid", "Reference"),
        _line("L1", "L1A", "Solid", "Measurement"),
    ]

    if v_int_fmt is not None:
        virtual_points = {"v_int": v_int_fmt}
        elements.extend([
            _line("B", "v_int", "Dashed", "Reference"),
            _line("L1A", "v_int", "Dashed", "Reference"),
            _angle("v_int", "B", "L1A", role="Measurement"),
        ])
        return {"VirtualPoints": virtual_points, "Elements": elements}

    return {"VirtualPoints": None, "Elements": elements}


def _l1_nb_distance_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["L1", "N", "B"]
    if not _has_points(landmarks, required):
        return None
    l1, n, b = (landmarks[k] for k in required)
    foot = _project_point_onto_line(l1, n, b)
    foot_fmt = _format_point(foot)
    if foot_fmt is None:
        return None
    virtual_points = {"v_l1_on_nb": foot_fmt}
    elements = [
        _line("N", "B", "Solid", "Reference"),
        _line("L1", "v_l1_on_nb", "Dashed", "Measurement"),
    ]
    return {"VirtualPoints": virtual_points, "Elements": elements}


def _u1_l1_angle_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """U1_L1_Inter_Incisor_Angle：上/下切牙轴线夹角，增加角度圆弧。"""
    required = ["UI", "U1A", "L1", "L1A"]
    if not _has_points(landmarks, required):
        return None

    ui, u1a, l1, l1a = (landmarks[k] for k in required)
    v_int = _get_intersection_point(ui, u1a, l1, l1a)
    v_int_fmt = _format_point(v_int) if v_int is not None else None

    elements = [
        _line("UI", "U1A", "Solid", "Measurement"),
        _line("L1", "L1A", "Solid", "Measurement"),
    ]

    if v_int_fmt is not None:
        virtual_points = {"v_int": v_int_fmt}
        elements.extend([
            _line("U1A", "v_int", "Dashed", "Reference"),
            _line("L1A", "v_int", "Dashed", "Reference"),
            _angle("v_int", "U1A", "L1A", role="Measurement"),
        ])
        return {"VirtualPoints": virtual_points, "Elements": elements}

    return {"VirtualPoints": None, "Elements": elements}


def _y_axis_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """Y_Axis_Angle：SGn 与 FH(Po-Or) 的夹角，增加角度圆弧。"""
    required = ["S", "Gn", "Or", "Po"]
    if not _has_points(landmarks, required):
        return None

    s, gn, or_pt, po = (landmarks[k] for k in required)
    v_int = _get_intersection_point(s, gn, po, or_pt)
    v_int_fmt = _format_point(v_int) if v_int is not None else None

    elements = [
        _line("S", "Gn", "Solid", "Measurement"),
        _line("Or", "Po", "Dashed", "Reference"),
    ]

    if v_int_fmt is not None:
        virtual_points = {"v_int": v_int_fmt}
        elements.extend([
            _line("Gn", "v_int", "Dashed", "Reference"),
            _line("Or", "v_int", "Dashed", "Reference"),
            _angle("v_int", "Gn", "Or", role="Measurement"),
        ])
        return {"VirtualPoints": virtual_points, "Elements": elements}

    return {"VirtualPoints": None, "Elements": elements}


def _mandibular_growth_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """Mandibular_Growth_Angle：BN 与 PtGn 的夹角，增加角度圆弧。"""
    required = ["Ba", "N", "Pt", "Gn"]
    if not _has_points(landmarks, required):
        return None

    ba, n, pt, gn = (landmarks[k] for k in required)
    v_int = _get_intersection_point(ba, n, pt, gn)
    v_int_fmt = _format_point(v_int) if v_int is not None else None

    elements = [
        _line("Ba", "N", "Solid", "Reference"),
        _line("Pt", "Gn", "Solid", "Measurement"),
    ]

    if v_int_fmt is not None:
        virtual_points = {"v_int": v_int_fmt}
        elements.extend([
            _line("N", "v_int", "Dashed", "Reference"),
            _line("Gn", "v_int", "Dashed", "Reference"),
            _angle("v_int", "N", "Gn", role="Measurement"),
        ])
        return {"VirtualPoints": virtual_points, "Elements": elements}

    return {"VirtualPoints": None, "Elements": elements}


def _sn_mp_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """SN_MP_Angle：SN 与 MP(Go-Me) 的夹角，增加角度圆弧。"""
    required = ["S", "N", "Go", "Me"]
    if not _has_points(landmarks, required):
        return None

    s, n, go, me = (landmarks[k] for k in required)
    v_int = _get_intersection_point(s, n, go, me)
    v_int_fmt = _format_point(v_int) if v_int is not None else None

    elements = [
        _line("S", "N", "Solid", "Reference"),
        _line("Go", "Me", "Solid", "Reference"),
    ]

    if v_int_fmt is not None:
        virtual_points = {"v_int": v_int_fmt}
        elements.extend([
            _line("N", "v_int", "Dashed", "Reference"),
            _line("Me", "v_int", "Dashed", "Reference"),
            _angle("v_int", "N", "Me", role="Measurement"),
        ])
        return {"VirtualPoints": virtual_points, "Elements": elements}

    return {"VirtualPoints": None, "Elements": elements}


def _u1_pp_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """U1-PP：UI 到 PP(ANS-PNS) 的垂距，必须画垂线（UI->PP垂足）。"""
    required = ["UI", "ANS", "PNS"]
    if not _has_points(landmarks, required):
        return None

    ui, ans, pns = (landmarks[k] for k in required)
    foot = _project_point_onto_line(ui, ans, pns)
    foot_fmt = _format_point(foot)
    if foot_fmt is None:
        return None

    virtual_points = {"v_u1_on_pp": foot_fmt}
    elements = [
        _line("ANS", "PNS", "Dashed", "Reference"),
        _line("UI", "v_u1_on_pp", "Dashed", "Measurement"),
    ]
    return {"VirtualPoints": virtual_points, "Elements": elements}


def _l1_mp_height_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """L1-MP：L1 到 MP(Go-Me) 的垂距，必须画垂线。"""
    required = ["L1", "Go", "Me"]
    if not _has_points(landmarks, required):
        return None

    l1, go, me = (landmarks[k] for k in required)
    foot = _project_point_onto_line(l1, go, me)
    foot_fmt = _format_point(foot)
    if foot_fmt is None:
        return None

    virtual_points = {"v_l1_on_mp": foot_fmt}
    elements = [
        _line("Go", "Me", "Solid", "Reference"),
        _line("L1", "v_l1_on_mp", "Dashed", "Measurement"),
    ]
    return {"VirtualPoints": virtual_points, "Elements": elements}


def _u6_pp_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """U6-PP：U6 到 PP(ANS-PNS) 的垂距，必须画垂线。"""
    required = ["U6", "ANS", "PNS"]
    if not _has_points(landmarks, required):
        return None

    u6, ans, pns = (landmarks[k] for k in required)
    foot = _project_point_onto_line(u6, ans, pns)
    foot_fmt = _format_point(foot)
    if foot_fmt is None:
        return None

    virtual_points = {"v_u6_on_pp": foot_fmt}
    elements = [
        _line("ANS", "PNS", "Dashed", "Reference"),
        _line("U6", "v_u6_on_pp", "Dashed", "Measurement"),
    ]
    return {"VirtualPoints": virtual_points, "Elements": elements}


def _l6_mp_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """L6-MP：L6 到 MP(Go-Me) 的垂距，必须画垂线。"""
    required = ["L6", "Go", "Me"]
    if not _has_points(landmarks, required):
        return None

    l6, go, me = (landmarks[k] for k in required)
    foot = _project_point_onto_line(l6, go, me)
    foot_fmt = _format_point(foot)
    if foot_fmt is None:
        return None

    virtual_points = {"v_l6_on_mp": foot_fmt}
    elements = [
        _line("Go", "Me", "Solid", "Reference"),
        _line("L6", "v_l6_on_mp", "Dashed", "Measurement"),
    ]
    return {"VirtualPoints": virtual_points, "Elements": elements}


def _mandibular_growth_type_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """Mandibular_Growth_Type_Angle: 绘制 S-N-Ar-Go-Me 折线，并标注三个关键角度。"""
    required = ["S", "N", "Ar", "Go", "Me"]
    if not _has_points(landmarks, required):
        return None

    elements = [
        # 绘制 S-N-Ar-Go-Me 折线作为参考
        _line("S", "N", "Solid", "Reference"),
        _line("S", "Ar", "Solid", "Reference"),
        _line("Ar", "Go", "Solid", "Reference"),
        _line("Go", "Me", "Solid", "Reference"),
        # 绘制三个角度
        _angle("S", "N", "Ar", role="Measurement"),  # ∠NSAr
        _angle("Ar", "S", "Go", role="Measurement"),  # ∠SArGo
        _angle("Go", "Ar", "Me", role="Measurement"),  # ∠ArGoMe
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _sn_length_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["S", "N"]
    if not _has_points(landmarks, required):
        return None
    elements = [_line("S", "N", "Solid", "Measurement")]
    return {"VirtualPoints": None, "Elements": elements}


def _go_me_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["Go", "Me"]
    if not _has_points(landmarks, required):
        return None
    elements = [_line("Go", "Me", "Solid", "Measurement")]
    return {"VirtualPoints": None, "Elements": elements}


def _airway_gap_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """构建气道区域可视化。

    - 几何外轮廓：使用 11 个专用点形成闭合多边形（质心-极角排序）
    - 测量连线：根据医学定义补充 5 条前后径测量线段
        PNS-UPW, SPP-SPPW, U-MPW, TB-TPPW, V-LPW

    采用“质心-极角排序”对已检测到的点进行环绕排序，尽可能形成外轮廓，
    保证任意点缺失情况下也能输出稳定的多边形（>=3点时）。
    """
    # 11点的短键（与 KEYPOINT_MAP_11 的键一致）
    keys_11 = [
        "U", "V", "UPW", "SPP", "SPPW", "MPW", "LPW", "TB", "TPPW", "AD", "Dprime"
    ]

    pts: List[np.ndarray] = []
    for k in keys_11:
        p = landmarks.get(k)
        if isinstance(p, np.ndarray) and p.shape[0] >= 2 and not np.isnan(p).any():
            pts.append(p.astype(float))
    # 也兼容全名（比如 "D'" 等），以防前端/上游用了全名做了覆盖
    fallback_full_names = [
        "Uvula tip", "Vallecula", "Upper Pharyngeal Wall", "Soft Palate Point",
        "Soft Palate Pharyngeal Wall", "Middle Pharyngeal Wall", "Lower Pharyngeal Wall",
        "Tongue Base", "Tongue Posterior Pharyngeal Wall", "Adenoid", "D'"
    ]
    for name in fallback_full_names:
        if len(pts) >= 11:
            break
        p = landmarks.get(name)
        if isinstance(p, np.ndarray) and p.shape[0] >= 2 and not np.isnan(p).any():
            # 避免重复
            if not any(np.allclose(p, q) for q in pts):
                pts.append(p.astype(float))

    # 如有至少 3 个点，则构建闭合轮廓多边形
    polygon: Optional[List[float]] = None
    if len(pts) >= 3:
        # 使用质心-极角排序，获得一个非自交的闭合轮廓
        arr = np.vstack(pts)  # (n,2)
        centroid = np.mean(arr, axis=0)
        angles = np.arctan2(arr[:, 1] - centroid[1], arr[:, 0] - centroid[0])
        order = np.argsort(angles)
        ordered = arr[order]

        contour: List[float] = []
        for p in ordered:
            contour.extend([float(p[0]), float(p[1])])
        polygon = contour

    # 根据医学定义补充 5 条测量线（存在即画，允许部分缺失）
    elements: List[Dict[str, str]] = []
    airway_pairs = [
        ("PNS", "UPW"),   # 鼻咽段
        ("SPP", "SPPW"),  # 口咽段（腭咽段）
        ("U", "MPW"),     # 口咽段（腭咽段）
        ("TB", "TPPW"),   # 口咽段（舌咽段）
        ("V", "LPW"),     # 喉咽段
    ]
    for a, b in airway_pairs:
        if _has_points(landmarks, [a, b]):
            elements.append(_line(a, b, "Dashed", "Measurement"))

    # 若既没有多边形也没有测量线，则认为无法构建可视化
    if polygon is None and not elements:
        return None

    return {
        "VirtualPoints": None,
        "Elements": elements,
        "Polygon": polygon,
    }


def _adenoid_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """腺样体 A/N 比值几何可视化。

    参考文档《腺体气道集成与后处理说明.md》：
    - N 值：PNS-D' 的直线距离
    - A 值：AD 点到 Ba-Ar 参考线的垂直距离
    """
    # 需要同时获取：AD, D'（11点）以及 PNS, Ba, Ar（25点）
    required = ["AD", "D'", "PNS", "Ba", "Ar"]
    if not _has_points(landmarks, required):
        return None

    ad, _dprime, _pns, ba, ar = (landmarks[k] for k in required)

    # 计算 AD 点到 Ba-Ar 直线的垂足
    foot = _project_point_onto_line(ad, ba, ar)
    foot_fmt = _format_point(foot)
    if foot_fmt is None:
        return None

    virtual_points = {"v_ad_on_baar": foot_fmt}
    elements = [
        _line("PNS", "D'", "Solid", "Measurement"),         # N 值：PNS-D'
        _line("Ba", "Ar", "Solid", "Reference"),            # 参考线：Ba-Ar
        _line("AD", "v_ad_on_baar", "Dashed", "Measurement"),  # A 值：AD 到 Ba-Ar 垂足
    ]
    return {"VirtualPoints": virtual_points, "Elements": elements}


def _line(from_label: str, to_label: str, style: str, role: str) -> Dict[str, str]:
    return {"Type": "Line", "From": from_label, "To": to_label, "Style": style, "Role": role}


def _angle(vertex: str, point1: str, point2: str, role: str) -> Dict[str, str]:
    """角度可视化元素。

    定义：以 vertex 为顶点，边分别为 vertex->point1 与 vertex->point2。

    前端应根据该三点绘制圆弧，并（可选）标注角度值。
    """
    return {"Type": "Angle", "Vertex": vertex, "Point1": point1, "Point2": point2, "Role": role}


def _get_intersection_point(
    p1: np.ndarray,
    p2: np.ndarray,
    p3: np.ndarray,
    p4: np.ndarray,
) -> Optional[np.ndarray]:
    """计算直线 p1-p2 与 p3-p4 的交点。

    返回：
        - np.ndarray(shape=(2,)) 交点
        - None：两直线平行或退化

    注：这里按“无限延长线”求交点（不是线段相交）。
    """
    p1 = np.asarray(p1, dtype=float)
    p2 = np.asarray(p2, dtype=float)
    p3 = np.asarray(p3, dtype=float)
    p4 = np.asarray(p4, dtype=float)

    d1 = p2 - p1
    d2 = p4 - p3

    denom = float(np.cross(d1, d2))
    if abs(denom) < 1e-8:
        return None

    t = float(np.cross(p3 - p1, d2) / denom)
    return p1 + t * d1


def _project_point_onto_line(point: np.ndarray, line_start: np.ndarray, line_end: np.ndarray) -> np.ndarray:
    """计算 point 在 line_start-line_end 直线上的投影点（垂足）。

    退化情况（line_start≈line_end）返回 line_start。
    """
    vec = line_end - line_start
    denom = float(np.dot(vec, vec))
    if denom < 1e-8:
        return line_start
    ratio = float(np.dot(point - line_start, vec) / denom)
    return line_start + ratio * vec


def _format_point(pt: Optional[np.ndarray]) -> Optional[List[float]]:
    if pt is None:
        return None
    arr = np.asarray(pt, dtype=float)
    if arr.shape[0] < 2 or np.isnan(arr).any():
        return None
    return [round(float(arr[0]), 2), round(float(arr[1]), 2)]


def _has_points(landmarks: Dict[str, np.ndarray], labels: List[str]) -> bool:
    return all(label in landmarks for label in labels)


def _normalize_landmarks(coordinates: Dict[str, Any]) -> Dict[str, np.ndarray]:
    """仅规范化25点：P-id -> 短标签。保留旧用法。"""
    normalized: Dict[str, np.ndarray] = {}
    for pid, point in coordinates.items():
        if pid not in KEYPOINT_MAP:
            continue
        alias = KEYPOINT_MAP[pid]
        arr = np.asarray(point, dtype=float)
        if arr.shape[0] < 2 or np.isnan(arr).any():
            continue
        normalized[alias] = arr
    return normalized


def _normalize_landmarks_all(coords25: Dict[str, Any], coords11: Dict[str, Any]) -> Dict[str, np.ndarray]:
    """合并规范化：25点(P-id->短标签) + 11点(直接key即短标签)。"""
    normalized: Dict[str, np.ndarray] = {}
    # 25点
    for pid, point in (coords25 or {}).items():
        if pid in KEYPOINT_MAP:
            alias = KEYPOINT_MAP[pid]
            arr = np.asarray(point, dtype=float)
            if arr.shape[0] >= 2 and not np.isnan(arr).any():
                normalized[alias] = arr
    # 11点
    for key, point in (coords11 or {}).items():
        # key 与 KEYPOINT_MAP_11 的键一致（U, V, ...）
        if key in KEYPOINT_MAP_11:
            arr = np.asarray(point, dtype=float)
            if arr.shape[0] >= 2 and not np.isnan(arr).any():
                normalized[key] = arr
            # 同时支持映射到人类可读的短标签别名（不必，但以防前端使用全名）
            alias_full = KEYPOINT_MAP_11[key]
            normalized[alias_full] = arr
    return normalized


def _extract_coordinates(landmarks_block: Dict[str, Any]) -> Dict[str, Any]:
    """支持两种输入：{'coordinates': {...}} 或直接传坐标 dict。"""
    if not isinstance(landmarks_block, dict):
        return {}
    if "coordinates" in landmarks_block:
        coords = landmarks_block.get("coordinates") or {}
        return coords if isinstance(coords, dict) else {}
    return landmarks_block

