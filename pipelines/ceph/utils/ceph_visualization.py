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


def _sna_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["S", "N", "A"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("S", "N", "Solid", "Reference"),
        _line("N", "A", "Solid", "Measurement"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _snb_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["S", "N", "B"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("S", "N", "Solid", "Reference"),
        _line("N", "B", "Solid", "Measurement"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _anb_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["S", "N", "A", "B"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("S", "N", "Solid", "Reference"),
        _line("N", "A", "Solid", "Measurement"),
        _line("N", "B", "Solid", "Measurement"),
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
    required = ["A", "B", "Or", "Po"]
    if not _has_points(landmarks, required):
        return None
    a, b, or_pt, po = (landmarks[k] for k in required)

    foot_a = _project_point_onto_line(a, po, or_pt)
    foot_b = _project_point_onto_line(b, po, or_pt)
    foot_a_fmt = _format_point(foot_a)
    foot_b_fmt = _format_point(foot_b)
    if foot_a_fmt is None or foot_b_fmt is None:
        return None

    virtual_points = {
        "v_a_on_fh": foot_a_fmt,
        "v_b_on_fh": foot_b_fmt,
    }
    elements = [
        _line("Po", "Or", "Dashed", "Reference"),
        _line("A", "v_a_on_fh", "Dashed", "Measurement"),
        _line("B", "v_b_on_fh", "Dashed", "Measurement"),
    ]
    return {"VirtualPoints": virtual_points, "Elements": elements}


def _fh_mp_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["Po", "Or", "Go", "Me"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("Po", "Or", "Dashed", "Reference"),
        _line("Go", "Me", "Solid", "Reference"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _u1_sn_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["S", "N", "UI", "U1A"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("S", "N", "Solid", "Reference"),
        _line("UI", "U1A", "Solid", "Measurement"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _impa_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["Go", "Me", "L1", "L1A"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("Go", "Me", "Solid", "Reference"),
        _line("L1", "L1A", "Solid", "Measurement"),
    ]
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
    required = ["PTM", "ANS"]
    if not _has_points(landmarks, required):
        return None
    elements = [_line("PTM", "ANS", "Solid", "Measurement")]
    return {"VirtualPoints": None, "Elements": elements}


def _ptm_s_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["PTM", "S"]
    if not _has_points(landmarks, required):
        return None
    elements = [_line("PTM", "S", "Solid", "Measurement")]
    return {"VirtualPoints": None, "Elements": elements}


def _pcd_s_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["Pcd", "S"]
    if not _has_points(landmarks, required):
        return None
    elements = [_line("Pcd", "S", "Solid", "Measurement")]
    return {"VirtualPoints": None, "Elements": elements}


def _u1_na_angle_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["N", "A", "UI", "U1A"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("N", "A", "Solid", "Reference"),
        _line("UI", "U1A", "Solid", "Measurement"),
    ]
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
    required = ["L1", "L1A", "Po", "Or"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("Po", "Or", "Dashed", "Reference"),
        _line("L1", "L1A", "Solid", "Measurement"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _l1_nb_angle_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["N", "B", "L1", "L1A"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("N", "B", "Solid", "Reference"),
        _line("L1", "L1A", "Solid", "Measurement"),
    ]
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
    required = ["UI", "U1A", "L1", "L1A"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("UI", "U1A", "Solid", "Measurement"),
        _line("L1", "L1A", "Solid", "Measurement"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _y_axis_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["S", "Gn", "Or", "Po"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("S", "Gn", "Solid", "Measurement"),
        _line("Or", "Po", "Dashed", "Reference"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _mandibular_growth_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["Ba", "N", "Pt", "Gn"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("Ba", "N", "Solid", "Reference"),
        _line("Pt", "Gn", "Solid", "Measurement"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _sn_mp_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["S", "N", "Go", "Me"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("S", "N", "Solid", "Reference"),
        _line("Go", "Me", "Solid", "Reference"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _u1_pp_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["UI", "ANS", "PNS"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("ANS", "PNS", "Dashed", "Reference"),
        _line("UI", "ANS", "Dashed", "Measurement"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _l1_mp_height_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["L1", "Go", "Me"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("Go", "Me", "Solid", "Reference"),
        _line("L1", "Go", "Dashed", "Measurement"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _u6_pp_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["U6", "ANS", "PNS"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("ANS", "PNS", "Dashed", "Reference"),
        _line("U6", "ANS", "Dashed", "Measurement"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _l6_mp_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["L6", "Go", "Me"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("Go", "Me", "Solid", "Reference"),
        _line("L6", "Go", "Dashed", "Measurement"),
    ]
    return {"VirtualPoints": None, "Elements": elements}


def _mandibular_growth_type_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    required = ["S", "N", "Ar", "Go", "Me"]
    if not _has_points(landmarks, required):
        return None
    elements = [
        _line("S", "N", "Solid", "Reference"),
        _line("S", "Ar", "Solid", "Reference"),
        _line("Ar", "Go", "Solid", "Reference"),
        _line("Go", "Me", "Solid", "Reference"),
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
    """构建气道区域可视化：直接使用 11 个专用点形成闭合多边形。

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

    if len(pts) < 3:
        return None

    # 使用质心-极角排序，获得一个非自交的闭合轮廓
    arr = np.vstack(pts)  # (n,2)
    centroid = np.mean(arr, axis=0)
    angles = np.arctan2(arr[:, 1] - centroid[1], arr[:, 0] - centroid[0])
    order = np.argsort(angles)
    ordered = arr[order]

    contour: List[float] = []
    for p in ordered:
        contour.extend([float(p[0]), float(p[1])])

    return {
        "VirtualPoints": None,
        "Elements": [],
        "Polygon": contour,
    }


def _adenoid_payload(landmarks: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    # 缺乏具体点位，使用 PNS 作为占位参考
    if "PNS" not in landmarks:
        return None
    elements = [_line("PNS", "PNS", "Dashed", "Reference")]
    return {"VirtualPoints": None, "Elements": elements}


def _line(from_label: str, to_label: str, style: str, role: str) -> Dict[str, str]:
    return {"Type": "Line", "From": from_label, "To": to_label, "Style": style, "Role": role}


def _project_point_onto_line(point: np.ndarray, line_start: np.ndarray, line_end: np.ndarray) -> np.ndarray:
    """计算 point 到 line_start-line_end 的垂足；退化向量返回起点。"""
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

