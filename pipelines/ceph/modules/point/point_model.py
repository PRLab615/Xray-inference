"""Ceph model wrapper for keypoint detection (modules copy)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import torch
from ultralytics import YOLO
from pipelines.ceph.utils.ceph_report import calculate_measurements
from pipelines.ceph.modules.point.pre_post import (
    preprocess_image,
    postprocess_results,
)
from tools.weight_fetcher import ensure_weight_file, WeightFetchError
from tools.timer import timer


logger = logging.getLogger(__name__)

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
        self.device = self._normalize_device(device)
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
            1. 显式传入且存在的本地路径（或可通过 S3 下载）
            2. 配置的 weights_key（从 config.yaml 传入，可通过 S3 下载）
            3. 环境变量 CEPH_MODEL_WEIGHTS（可选覆盖）
        
        注意：权重路径应在 config.yaml 中统一配置，不再使用硬编码的默认路径。
        """
        # 检查环境变量（可选覆盖）
        env_weights = os.getenv("CEPH_MODEL_WEIGHTS")
        
        candidates = [
            ("explicit", explicit_path),
            ("weights_key", self.weights_key),
            ("env", env_weights),
        ]
        
        for origin, candidate in candidates:
            if not candidate:
                continue

            # 如果是本地存在的文件，直接返回
            if os.path.exists(candidate):
                self.logger.info("Using local weights file: %s (from %s)", candidate, origin)
                return candidate

            # 尝试从 S3 下载（仅对 explicit 和 weights_key）
            if origin in {"explicit", "weights_key"}:
                try:
                    downloaded = ensure_weight_file(candidate, force_download=self.weights_force_download)
                    self.logger.info("Downloaded Ceph weights from S3 key '%s' to %s", candidate, downloaded)
                    return downloaded
                except WeightFetchError:
                    continue
        
        # 所有候选路径都失败，抛出明确的错误
        checked = []
        if explicit_path:
            checked.append(f"explicit path '{explicit_path}'")
        if self.weights_key:
            checked.append(f"weights_key '{self.weights_key}'")
        if env_weights:
            checked.append(f"env CEPH_MODEL_WEIGHTS '{env_weights}'")
        
        error_msg = (
            f"Ceph model weights not found. Checked: {', '.join(checked) if checked else 'none'}. "
            f"Please configure weights_key in config.yaml or provide explicit weights_path."
        )
        raise FileNotFoundError(error_msg)

    def __init__model(self) -> YOLO:
        if not os.path.exists(self.weights_path):
            raise FileNotFoundError(
                f"Ceph model weights not found: {self.weights_path}"
            )
        self.logger.info("Loading Ceph model weights: %s", self.weights_path)
        model = YOLO(self.weights_path)
        if self.device != "cpu":
            try:
                model.to(self.device)
                self.logger.info("Ceph YOLO model moved to %s", self.device)
            except Exception as exc:
                self.logger.warning("Failed to move Ceph model to %s: %s", self.device, exc)
        return model

    def _normalize_device(self, device: Optional[str]) -> str:
        """
        将配置的 device 统一转换为 PyTorch/Ultralytics 可识别的格式。
        """
        if not torch.cuda.is_available():
            return "cpu"

        if device is None:
            return "cuda:0"

        device_str = str(device).strip()
        if device_str.lower() == "cpu":
            return "cpu"

        if device_str.lower().startswith("cuda"):
            return device_str.lower()

        if device_str.isdigit():
            return f"cuda:{device_str}"

        # 回退：直接返回原始字符串（例如自定义 "cuda:1"）
        return device_str

    def predict(self, image_path: str) -> LandmarkResult:
        """
        执行关键点检测推理
        
        Args:
            image_path: 图像文件路径
            
        Returns:
            LandmarkResult: 关键点检测结果
        """
        # 1. 前处理：验证图像路径
        with timer.record("ceph_point.pre"):
            processed_path = preprocess_image(image_path, self.logger)
        
        # 2. YOLO 推理
        with timer.record("ceph_point.inference"):
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

        # 3. 后处理：提取关键点和置信度
        with timer.record("ceph_point.post"):
            landmark_result = postprocess_results(results, processed_path, self.weights_path, self.logger)
        
        return landmark_result


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

        # 关键点检测（内部已埋点 ceph_point.pre/inference/post）
        landmark_result = self.detector.predict(image_path)
        
        # 测量计算
        with timer.record("ceph_point.measurement"):
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

