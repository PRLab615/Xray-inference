# -*- coding: utf-8 -*-
"""
侧位片34点轮廓检测模型封装
"""
import logging
from typing import Any, Dict, Optional, NamedTuple
from ultralytics import YOLO

from pipelines.ceph.modules.point.point_model import CephModel
from pipelines.ceph.modules.point_lunkuo_34.pre_post import (
    preprocess_image,
    postprocess_results,
)
from tools.timer import timer

class LandmarkResult34(NamedTuple):
    """34点轮廓检测结果的数据结构"""
    coordinates: Dict[str, Any]  # { "P1": [x, y], ... }
    confidences: Dict[str, float] # { "P1": 0.95, ... }
    status: str

class PointLunkuo34Model(CephModel):
    """
    34点轮廓检测模型
    """
    def predict(self, image_path: str) -> LandmarkResult34:
        """
        执行推理
        """
        # 1. 前处理
        with timer.record("ceph_point34.pre"):
            processed_path = preprocess_image(image_path, self.logger)
        
        # 2. 推理
        with timer.record("ceph_point34.inference"):
            model = self._ensure_model()
            self.logger.info("Running Point34 contour detection on %s", processed_path)
            results = model.predict(
                source=processed_path,
                imgsz=self.image_size,
                device=self.device,
                conf=self.conf,
                iou=self.iou,
                max_det=self.max_det,
                verbose=False,
            )

        # 3. 后处理
        with timer.record("ceph_point34.post"):
            landmark_result = postprocess_results(results, processed_path, self.weights_path, self.logger)
            
        return landmark_result

    @staticmethod
    def landmark_result_to_dict(result: LandmarkResult34) -> Dict[str, Any]:
        """将结果转换为字典格式"""
        return {
            "coordinates": result.coordinates,
            "confidences": result.confidences,
            "status": result.status
        }
