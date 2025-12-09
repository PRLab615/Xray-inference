"""CVM model wrapper for cervical vertebral maturity stage detection."""

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import torch
from ultralytics import YOLO

from pipelines.ceph.modules.CVM.pre_post import (
    preprocess_image,
    postprocess_results,
)
from tools.weight_fetcher import ensure_weight_file, WeightFetchError
from tools.timer import timer

logger = logging.getLogger(__name__)


@dataclass
class CVMResult:
    """用于颈椎成熟度检测的结构化输出。"""

    coordinates: List[List[int]]  # area边界框的四个顶点
    level: int  # CS阶段 (1-6) 或 0 (无效)
    confidence: float
    image_path: str
    weights_path: str
    status: str = "ok"


class CVMModel:
    """
    封装底层的 Ultralytics YOLO 模型，负责模型加载和推理。
    """

    def __init__(
        self,
        weights_path: Optional[str] = None,
        weights_key: Optional[str] = None,
        weights_force_download: bool = False,
        device: str = "0",
        conf: float = 0.25,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.weights_force_download = weights_force_download
        self.weights_key = weights_key
        self.weights_path = self._resolve_weights_path(weights_path)
        self.device = self._normalize_device(device)
        self.conf = conf

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
            3. 环境变量 CVM_MODEL_WEIGHTS（可选覆盖）
        """
        # 检查环境变量（可选覆盖）
        env_weights = os.getenv("CVM_MODEL_WEIGHTS")

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
                self.logger.info("Using local CVM weights file: %s (from %s)", candidate, origin)
                return candidate

            # 尝试从 S3 下载（仅对 explicit 和 weights_key）
            if origin in {"explicit", "weights_key"}:
                try:
                    downloaded = ensure_weight_file(candidate, force_download=self.weights_force_download)
                    self.logger.info("Downloaded CVM weights from S3 key '%s' to %s", candidate, downloaded)
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
            checked.append(f"env CVM_MODEL_WEIGHTS '{env_weights}'")

        error_msg = (
            f"CVM model weights not found. Checked: {', '.join(checked) if checked else 'none'}. "
            f"Please configure weights_key in config.yaml or provide explicit weights_path."
        )
        raise FileNotFoundError(error_msg)

    def __init__model(self) -> YOLO:
        if not os.path.exists(self.weights_path):
            raise FileNotFoundError(
                f"CVM model weights not found: {self.weights_path}"
            )
        self.logger.info("Loading CVM model weights: %s", self.weights_path)
        model = YOLO(self.weights_path)
        if self.device != "cpu":
            try:
                model.to(self.device)
                self.logger.info("CVM YOLO model moved to %s", self.device)
            except Exception as exc:
                self.logger.warning("Failed to move CVM model to %s: %s", self.device, exc)
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

    def predict(self, image_path: str) -> CVMResult:
        """
        执行颈椎成熟度检测推理

        Args:
            image_path: 图像文件路径

        Returns:
            CVMResult: 颈椎成熟度检测结果
        """
        # 1. 前处理：验证图像路径并读取图像尺寸
        with timer.record("ceph_cvm.pre"):
            processed_path, img_height, img_width = preprocess_image(image_path, self.logger)

        # 2. YOLO 推理
        with timer.record("ceph_cvm.inference"):
            model = self._ensure_model()
            self.logger.info("Running CVM detection on %s", processed_path)
            
            # 读取图像（用于推理）
            import cv2
            img = cv2.imread(processed_path)
            if img is None:
                raise ValueError(f"无法读取图像: {processed_path}")

            # 模型推理
            results = model.predict(img, conf=self.conf, save=False, verbose=False)
            predictions = results[0].boxes.cpu().numpy()

        # 3. 后处理：提取分期结果
        with timer.record("ceph_cvm.post"):
            cvm_result = postprocess_results(
                predictions, processed_path, self.weights_path, img_height, img_width, self.logger
            )

        return cvm_result


class CVMInferenceEngine:
    """
    封装CVMModel的高级编排器，生成最终的颈椎成熟度输出。
    """

    def __init__(
        self,
        *,
        weights_path: Optional[str] = None,
        weights_key: Optional[str] = None,
        weights_force_download: bool = False,
        device: str = "0",
        conf: float = 0.25,
    ):
        self.detector = CVMModel(
            weights_path=weights_path,
            weights_key=weights_key,
            weights_force_download=weights_force_download,
            device=device,
            conf=conf,
        )
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(
        self,
        image_path: str,
    ) -> Dict[str, Any]:
        """
        执行颈椎成熟度检测流程

        Args:
            image_path: 图像文件路径

        Returns:
            dict: 包含颈椎成熟度检测结果的字典，格式：
                {
                    "coordinates": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]],
                    "level": 1-6,
                    "confidence": 0.0-1.0,
                    "serialized_mask": ""  # 预留字段，当前为空
                }
        """
        self.logger.info("Running CVM inference on %s", image_path)

        # 执行检测
        cvm_result = self.detector.predict(image_path)

        # 转换为标准格式
        result = {
            "coordinates": cvm_result.coordinates,
            "level": cvm_result.level,
            "confidence": cvm_result.confidence,
            "serialized_mask": "",  # 预留字段，当前为空字符串
        }

        self.logger.info(
            "Completed CVM inference: level=%d, confidence=%.4f, status=%s",
            cvm_result.level,
            cvm_result.confidence,
            cvm_result.status,
        )
        return result

