# -*- coding: utf-8 -*-
"""
气道/腺体 11 点位标志点检测模块
用于检测侧位片中的 11 个气道和腺体相关标志点
"""

from pipelines.ceph.modules.point_11.point_11_model import (
    LandmarkResult11,
    Point11Model,
)

__all__ = [
    "LandmarkResult11",
    "Point11Model",
]

