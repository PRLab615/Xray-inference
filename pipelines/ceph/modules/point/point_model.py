"""Ceph model wrapper for keypoint detection (modules copy)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from ultralytics import YOLO
from pipelines.ceph.utils.ceph_report import calculate_measurements
from pipelines.ceph.modules.point.pre_post import (
    preprocess_image,
    postprocess_results,
)
from tools.weight_fetcher import ensure_weight_file, WeightFetchError


logger = logging.getLogger(__name__)
DEFAULT_WEIGHTS_PATH = os.getenv(
    "CEPH_MODEL_WEIGHTS",
    str(Path(__file__).resolve().parents[2] / "point_best_19.pt"),
)

@dataclass
class LandmarkResult:
    """用于头影测量标志点检测的结构化输出。"""

    coordinates: Dict[str, np.ndarray]
    confidences: Dict[str, float]
    detected: List[str]
    missing: List[str]
    image_path: str
    weights_path: str
    orig_shape: Optional[List[int]] = None
    status: str = "ok"


class CephModel:
    """
    封装底层的 Ultralytics YOLO 模型，负责模型加载和推理。
    前处理和后处理逻辑已提取到 modules/pre_post.py
    """

    def __init__(
        self,
        weights_path: Optional[str] = None,
        weights_key: Optional[str] = None,
        weights_force_download: bool = False,
        device: str = "0",
        image_size: int = 1024,
        conf: float = 0.25,
        iou: float = 0.6,
        max_det: int = 1,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.weights_force_download = weights_force_download
        self.weights_key = weights_key
        self.weights_path = self._resolve_weights_path(weights_path)
        self.device = device
        self.image_size = image_size
        self.conf = conf
        self.iou = iou
        self.max_det = max_det

        self._model: Optional[YOLO] = None
        self._ensure_model()

    def _ensure_model(self) -> YOLO:
        """确保模型已经加载到内存中"""
        if self._model is None:
            self._model = self.__init__model()
        return self._model

    def _resolve_weights_path(self, explicit_path: Optional[str]) -> str:
        """
        决定最终用于 YOLO 的权重文件。

        优先级：
            1. 显式传入且存在的本地路径
            2. 配置的 S3 Key（weights_path 作为 Key 或单独提供 weights_key）
            3. 默认内置路径
        """
        candidates = [
            ("explicit", explicit_path),
            ("weights_key", self.weights_key),
            ("default", DEFAULT_WEIGHTS_PATH),
        ]
        for origin, candidate in candidates:
            if not candidate:
                continue

            if os.path.exists(candidate):
                return candidate

            if origin in {"explicit", "weights_key"}:
                try:
                    downloaded = ensure_weight_file(candidate, force_download=self.weights_force_download)
                    self.logger.info("Downloaded Ceph weights from S3 key '%s' to %s", candidate, downloaded)
                    return downloaded
                except WeightFetchError:
                    continue

        raise FileNotFoundError(
            f"Ceph model weights not found. Checked explicit path, weights_key and default {DEFAULT_WEIGHTS_PATH}"
        )

    def __init__model(self) -> YOLO:
        if not os.path.exists(self.weights_path):
            raise FileNotFoundError(
                f"Ceph model weights not found: {self.weights_path}"
            )
        self.logger.info("Loading Ceph model weights: %s", self.weights_path)
        return YOLO(self.weights_path)



    def predict(self, image_path: str) -> LandmarkResult:
        """
        执行关键点检测推理
        
        Args:
            image_path: 图像文件路径
            
        Returns:
            LandmarkResult: 关键点检测结果
        """
        # 前处理：验证图像路径
        processed_path = preprocess_image(image_path, self.logger)
        
        # 加载模型并推理
        model = self._ensure_model()
        self.logger.info("Running Ceph keypoint detection on %s", processed_path)
        results = model.predict(
            source=processed_path,
            imgsz=self.image_size,
            device=self.device,
            conf=self.conf,
            iou=self.iou,
            max_det=self.max_det,
            verbose=False,
        )

        # 后处理：提取关键点和置信度
        return postprocess_results(results, processed_path, self.weights_path, self.logger)


class CephInferenceEngine:
    """
    封装CephModel和测量辅助工具的高级编排器
    以及JSON格式化器，以生成最终的头影测量输出。
    """

    def __init__(
        self,
        *,
        weights_path: Optional[str] = None,
        weights_key: Optional[str] = None,
        weights_force_download: bool = False,
        device: str = "0",
        image_size: int = 1024,
        conf: float = 0.25,
        iou: float = 0.6,
        max_det: int = 1,
    ):
        self.detector = CephModel(
            weights_path=weights_path,
            weights_key=weights_key,
            weights_force_download=weights_force_download,
            device=device,
            image_size=image_size,
            conf=conf,
            iou=iou,
            max_det=max_det,
        )
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(self, image_path: str, patient_info: Dict[str, str]) -> Dict[str, Any]:
        """
        Complete cephalometric workflow: preprocess -> detect -> compute measurements.
        （不负责 JSON 规范化，交给 pipeline 处理）
        """
        self._validate_patient_info(patient_info)
        self.logger.info("Running Ceph inference on %s", image_path)

        landmark_result = self.detector.predict(image_path)
        measurements = calculate_measurements(landmark_result.coordinates)

        inference_bundle = {
            "landmarks": self._landmark_result_to_dict(landmark_result),
            "measurements": measurements,
        }

        self.logger.info(
            "Completed Ceph inference: %s landmarks detected, %s measurements",
            len(landmark_result.detected),
            len(measurements),
        )
        return inference_bundle

    def _validate_patient_info(self, patient_info: Dict[str, str]):
        if not patient_info:
            raise ValueError("patient_info is required")

        gender = patient_info.get("gender")
        dental_age_stage = patient_info.get("DentalAgeStage")

        if gender not in {"Male", "Female"}:
            raise ValueError("gender must be 'Male' or 'Female'")
        if dental_age_stage not in {"Permanent", "Mixed"}:
            raise ValueError("DentalAgeStage must be 'Permanent' or 'Mixed'")

    @staticmethod
    def _landmark_result_to_dict(result: LandmarkResult) -> Dict[str, Any]:
        return {
            "coordinates": result.coordinates,
            "confidences": result.confidences,
            "detected": result.detected,
            "missing": result.missing,
            "image_path": result.image_path,
            "weights_path": result.weights_path,
            "orig_shape": result.orig_shape,
            "status": result.status,
        }

