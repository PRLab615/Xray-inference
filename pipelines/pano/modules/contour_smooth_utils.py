# -*- coding: utf-8 -*-
"""
轮廓平滑处理工具模块
迁移自前端 app.js 的平滑算法，用于后端统一处理轮廓优化
"""
import numpy as np
from typing import List, Tuple


def simplify_points_rdp(points: List[List[float]], tolerance: float = 2.0) -> List[List[float]]:
    """
    Ramer-Douglas-Peucker (RDP) 算法 - 抽稀点集

    作用：去除阶梯状像素点，保留关键拐点

    Args:
        points: 点集 [[x,y], [x,y], ...]
        tolerance: 容差（像素单位），建议 1.5 ~ 2.5
                  值越小保留细节越多但锯齿越多，值越大线条越直但可能变形

    Returns:
        简化后的点集 [[x,y], [x,y], ...]
    """
    if len(points) <= 2:
        return points

    def point_line_distance_sq(point, line_start, line_end):
        """计算点到线段的距离平方"""
        px, py = point
        x1, y1 = line_start
        x2, y2 = line_end

        dx = x2 - x1
        dy = y2 - y1

        if dx == 0 and dy == 0:
            return (px - x1) ** 2 + (py - y1) ** 2

        t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
        t = max(0, min(1, t))

        proj_x = x1 + t * dx
        proj_y = y1 + t * dy

        return (px - proj_x) ** 2 + (py - proj_y) ** 2

    def rdp_recursive(points_subset, first, last, tolerance_sq, result):
        """RDP 递归核心"""
        max_dist_sq = tolerance_sq
        index = first

        for i in range(first + 1, last):
            dist_sq = point_line_distance_sq(
                points_subset[i],
                points_subset[first],
                points_subset[last]
            )
            if dist_sq > max_dist_sq:
                max_dist_sq = dist_sq
                index = i

        if max_dist_sq > tolerance_sq:
            if index - first > 1:
                rdp_recursive(points_subset, first, index, tolerance_sq, result)
            result.append(points_subset[index])
            if last - index > 1:
                rdp_recursive(points_subset, index, last, tolerance_sq, result)

    tolerance_sq = tolerance * tolerance
    simplified = [points[0]]
    rdp_recursive(points, 0, len(points) - 1, tolerance_sq, simplified)
    simplified.append(points[-1])

    return simplified


def moving_average_smooth(points: List[List[float]], window_size: int = 5) -> List[List[float]]:
    """
    滑动平均平滑 - 去除突兀的毛刺

    作用：对每个点用周围点的平均值替代，消除局部噪点

    Args:
        points: 点集 [[x,y], [x,y], ...]
        window_size: 窗口大小（奇数，建议 3 或 5）
                    值越大越平滑，但细节丢失越多

    Returns:
        平滑后的点集 [[x,y], [x,y], ...]
    """
    if len(points) < 3:
        return points

    result = []
    offset = window_size // 2
    n = len(points)

    for i in range(n):
        sum_x = 0.0
        sum_y = 0.0

        # 计算窗口内的平均值（闭合轮廓，循环取点）
        for j in range(-offset, offset + 1):
            idx = (i + j) % n
            sum_x += points[idx][0]
            sum_y += points[idx][1]

        result.append([sum_x / window_size, sum_y / window_size])

    return result


def smooth_polyline_chaikin(points: List[List[float]], iterations: int = 3) -> List[List[float]]:
    """
    Chaikin 平滑算法 - 让轮廓圆润

    作用：在每条边上插入新点，让折线变曲线，消除尖锐转角

    Args:
        points: 点集 [[x,y], [x,y], ...]
        iterations: 平滑迭代次数，建议 1-3
                   迭代次数越多越圆润，但点数会指数增长

    Returns:
        平滑后的点集 [[x,y], [x,y], ...]
    """
    if len(points) < 3:
        return points

    current = points[:]

    for _ in range(iterations):
        smoothed = []
        n = len(current)

        for i in range(n):
            p0 = current[i]
            p1 = current[(i + 1) % n]

            # Chaikin 算法：在每条边上生成两个新点
            # Q点：距离 p0 更近 (75% p0 + 25% p1)
            # R点：距离 p1 更近 (25% p0 + 75% p1)
            q_x = 0.75 * p0[0] + 0.25 * p1[0]
            q_y = 0.75 * p0[1] + 0.25 * p1[1]

            r_x = 0.25 * p0[0] + 0.75 * p1[0]
            r_y = 0.25 * p0[1] + 0.75 * p1[1]

            smoothed.append([q_x, q_y])
            smoothed.append([r_x, r_y])

        current = smoothed

    return current


def apply_contour_smoothing(
        contour: List[List[float]],
        mode: str = "standard",
        rdp_tolerance: float = 2.0,
        moving_avg_window: int = 5,
        chaikin_iterations: int = 3
) -> List[List[float]]:
    """
    应用完整的轮廓平滑处理流程

    Args:
        contour: 原始轮廓点集 [[x,y], [x,y], ...]
        mode: 平滑模式
            - "standard": 标准流程（RDP + Chaikin，适用于大多数情况）
            - "aggressive": 强力平滑（滑动平均 + RDP + Chaikin，适用于噪点多的情况）
            - "light": 轻度平滑（仅 RDP）
            - "none": 不平滑（直接返回）
        rdp_tolerance: RDP 容差
        moving_avg_window: 滑动平均窗口大小
        chaikin_iterations: Chaikin 迭代次数

    Returns:
        平滑后的轮廓点集 [[x,y], [x,y], ...]
    """
    if not contour or len(contour) < 3:
        return contour

    if mode == "none":
        return contour

    result = contour[:]

    if mode == "aggressive":
        # 强力平滑：先滑动平均去毛刺 -> 再RDP抽稀 -> Chaikin平滑
        result = moving_average_smooth(result, moving_avg_window)
        result = simplify_points_rdp(result, rdp_tolerance)
        result = smooth_polyline_chaikin(result, chaikin_iterations)

    elif mode == "standard":
        # 标准流程：RDP抽稀 -> Chaikin平滑
        result = simplify_points_rdp(result, rdp_tolerance)
        result = smooth_polyline_chaikin(result, chaikin_iterations)

    elif mode == "light":
        # 轻度平滑：仅RDP抽稀
        result = simplify_points_rdp(result, rdp_tolerance)

    return result


# 预设的平滑配置（针对不同解剖结构）
SMOOTH_PRESETS = {
    "teeth": {
        "mode": "standard",
        "rdp_tolerance": 2.0,
        "chaikin_iterations": 3
    },
    "condyle": {
        "mode": "aggressive",
        "rdp_tolerance": 2.5,
        "moving_avg_window": 5,
        "chaikin_iterations": 4
    },
    "mandible": {
        "mode": "aggressive",
        "rdp_tolerance": 2.5,
        "moving_avg_window": 5,
        "chaikin_iterations": 4
    },
    "sinus": {
        "mode": "aggressive",
        "rdp_tolerance": 2.5,
        "moving_avg_window": 5,
        "chaikin_iterations": 4
    },
    "neural": {
        "mode": "aggressive",
        "rdp_tolerance": 2.5,
        "moving_avg_window": 5,
        "chaikin_iterations": 4
    },
    "alveolarcrest": {
        "mode": "standard",
        "rdp_tolerance": 2.0,
        "chaikin_iterations": 3
    }
}


def smooth_contour_by_preset(contour: List[List[float]], structure_type: str) -> List[List[float]]:
    """
    根据解剖结构类型应用预设的平滑配置

    Args:
        contour: 原始轮廓点集 [[x,y], [x,y], ...]
        structure_type: 解剖结构类型（如 "teeth", "condyle", "sinus" 等）

    Returns:
        平滑后的轮廓点集 [[x,y], [x,y], ...]
    """
    preset = SMOOTH_PRESETS.get(structure_type, SMOOTH_PRESETS["teeth"])
    return apply_contour_smoothing(contour, **preset)
