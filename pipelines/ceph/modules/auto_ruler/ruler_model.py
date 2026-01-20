
"""Ceph model wrapper for ruler detection."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import torch
from ultralytics import YOLO

from tools.weight_fetcher import ensure_weight_file, WeightFetchError
from tools.timer import timer


logger = logging.getLogger(__name__)


class RulerModel:
    """
    封装底层的 Ultralytics YOLO 模型，用于自动比例尺识别。
    """

    def __init__(
        self,
        weights_path: Optional[str] = None,
        weights_key: Optional[str] = None,
        weights_force_download: bool = False,
        device: str = "0",
        image_size: int = 1024,
        conf: float = 0.25,
        iou: float = 0.45,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.weights_force_download = weights_force_download
        self.weights_key = weights_key
        self.weights_path = self._resolve_weights_path(weights_path)
        self.device = self._normalize_device(device)
        self.image_size = image_size
        self.conf = conf
        self.iou = iou

        self._model: Optional[YOLO] = None
        self._ensure_model()

    def _ensure_model(self) -> YOLO:
        if self._model is None:
            self._model = self.__init__model()
        return self._model

    def _resolve_weights_path(self, explicit_path: Optional[str]) -> str:
        env_weights = os.getenv("RULER_MODEL_WEIGHTS")
        
        candidates = [
            ("explicit", explicit_path),
            ("weights_key", self.weights_key),
            ("env", env_weights),
        ]
        
        for origin, candidate in candidates:
            if not candidate:
                continue

            if os.path.exists(candidate):
                self.logger.info("Using local ruler weights file: %s (from %s)", candidate, origin)
                return candidate

            if origin in {"explicit", "weights_key"}:
                try:
                    downloaded = ensure_weight_file(candidate, force_download=self.weights_force_download)
                    self.logger.info("Downloaded ruler weights from S3 key '%s' to %s", candidate, downloaded)
                    return downloaded
                except WeightFetchError:
                    continue
        
        checked = []
        if explicit_path:
            checked.append(f"explicit path '{explicit_path}'")
        if self.weights_key:
            checked.append(f"weights_key '{self.weights_key}'")
        if env_weights:
            checked.append(f"env RULER_MODEL_WEIGHTS '{env_weights}'")
        
        error_msg = (
            f"Ruler model weights not found. Checked: {', '.join(checked) if checked else 'none'}. "
            f"Please configure 'auto_ruler.weights_key' in config.yaml."
        )
        raise FileNotFoundError(error_msg)

    def __init__model(self) -> YOLO:
        if not os.path.exists(self.weights_path):
            raise FileNotFoundError(f"Ruler model weights not found: {self.weights_path}")
        self.logger.info("Loading ruler model weights: %s", self.weights_path)
        model = YOLO(self.weights_path)
        if self.device != "cpu":
            try:
                model.to(self.device)
                self.logger.info("Ruler YOLO model moved to %s", self.device)
            except Exception as exc:
                self.logger.warning("Failed to move ruler model to %s: %s", self.device, exc)
        return model

    def _normalize_device(self, device: Optional[str]) -> str:
        if not torch.cuda.is_available():
            return "cpu"
        device_str = str(device).strip().lower()
        if not device_str or device_str == "cpu":
            return "cpu"
        if device_str.startswith("cuda") or device_str.isdigit():
            return f"cuda:{device_str.split(':')[-1]}" if ':' in device_str else f"cuda:{device_str}"
        return device_str

    def predict(self, image_path: str) -> Optional[Dict[str, Any]]:
        """
        执行比例尺检测推理，并返回标准格式的比例尺数据。
        
        Args:
            image_path: 图像文件路径
            
        Returns:
            A dictionary containing ruler info if successful, otherwise None.
            Example: {'points': [[x1, y1], [x2, y2]], 'distance_mm': 10}
        """
        model = self._ensure_model()
        self.logger.info("Running ruler detection on %s", image_path)

        with timer.record("ceph_ruler.inference"):
            results = model.predict(
                source=image_path,
                imgsz=self.image_size,
                device=self.device,
                conf=self.conf,
                iou=self.iou,
                verbose=False,
            )

        # 后处理逻辑：从 results 中提取两个点
        # 注意：这里的实现是示意性的，需要根据您模型的实际输出来调整
        if not results or not results[0].keypoints:
            self.logger.warning("Ruler detection returned no keypoints.")
            return None

        keypoints = results[0].keypoints.xy.cpu().numpy()
        if keypoints.shape[1] < 2:
            self.logger.warning(f"Ruler detection found only {keypoints.shape[1]} points, expected 2.")
            return None

        # 假设模型输出的类别0是比例尺，并且输出了两个点
        point1 = keypoints[0, 0, :].tolist()
        point2 = keypoints[0, 1, :].tolist()

        ruler_data = {
            "points": [point1, point2],
            "distance_mm": 10
        }
        
        self.logger.info(f"Auto ruler detected: {ruler_data}")
        return ruler_data
