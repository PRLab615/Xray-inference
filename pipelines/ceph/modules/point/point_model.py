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
from pipelines.ceph.utils.ceph_report import calculate_measurements, DEFAULT_SPACING_MM_PER_PIXEL
from pipelines.ceph.modules.point.pre_post import (
    preprocess_image,
    postprocess_results,
)
from tools.weight_fetcher import ensure_weight_file, WeightFetchError
from tools.timer import timer


logger = logging.getLogger(__name__)

# 默认像素间距（仅作为后备方案，应优先使用 DICOM metadata 中的真实值）
DEFAULT_BASE_SPACING = 0.1  # mm/pixel（经验值，不同设备可能不同）

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
    
    ⚠️ Spacing（像素间距）说明：
        - Spacing 决定了像素到毫米的转换系数，直接影响所有长度测量的准确性
        - **强烈建议**：在 patient_info 中提供 PixelSpacing（从 DICOM metadata 获取）
        - 如果未提供，将使用默认值 0.1 mm/pixel，但**测量结果可能不准确**
        
    为什么不能自动计算 spacing？
        - 不同设备的原始图像分辨率不同（2000px, 2400px, 3000px...）
        - 用户可能传入 JPG/PNG 等非 DICOM 文件，无法得知原始物理尺度
        - 没有物理参考标准（如标定板），无法从图像尺寸推断真实距离
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
        # Spacing 默认值（仅作为后备方案）
        default_spacing: float = DEFAULT_BASE_SPACING,
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
        self.default_spacing = default_spacing
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(
        self, 
        image_path: str, 
        patient_info: Dict[str, str],
        pixel_spacing: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Complete cephalometric workflow: preprocess -> detect -> compute measurements.
        （不负责 JSON 规范化，交给 pipeline 处理）
        
        Args:
            image_path: 图像文件路径
            patient_info: 患者信息（gender, DentalAgeStage, 可选 PixelSpacing）
            pixel_spacing: 外部传入的像素间距/比例尺信息（可选，优先级最高）
                - scale_x: 水平方向 1像素 = 多少mm
                - scale_y: 垂直方向 1像素 = 多少mm
                - source: 数据来源（"dicom" 或 "request"）
        
        比例尺优先级（从高到低）：
            1. pixel_spacing 参数（来自 DICOM 自动解析或请求参数）
            2. patient_info["PixelSpacing"]（原有方式，手动传入）
            3. self.default_spacing（默认值 0.1 mm/px，可能不准确）
        """
        self._validate_patient_info(patient_info)
        self.logger.info("Running Ceph inference on %s", image_path)

        # ===== 步骤 1: 关键点检测 =====
        landmark_result = self.detector.predict(image_path)
        
        # ===== 步骤 2: 确定 Spacing（像素间距）=====
        # 优先级：pixel_spacing 参数 > patient_info["PixelSpacing"] > 默认值
        if pixel_spacing and pixel_spacing.get("scale_x"):
            # 最高优先级：外部传入的 pixel_spacing（来自 DICOM 或请求参数）
            spacing = pixel_spacing["scale_x"]
            spacing_source = pixel_spacing.get("source", "external")
            self.logger.info(f"Using pixel spacing from {spacing_source}: {spacing:.4f} mm/px")
        else:
            # 回退到原有逻辑：patient_info["PixelSpacing"] 或默认值
            spacing = self._get_spacing(patient_info, landmark_result)
            spacing_source = "patient_info" if patient_info.get("PixelSpacing") else "default"
        
        # 从 patient_info 获取性别和牙列期
        sex = patient_info.get("gender", "Male").lower()
        dentition = patient_info.get("DentalAgeStage", "Permanent").lower()
        
        # 测量计算（传入 spacing 进行像素到毫米的转换）
        with timer.record("ceph_point.measurement"):
            measurements = calculate_measurements(
                landmark_result.coordinates,
                sex=sex,
                dentition=dentition,
                spacing=spacing,
            )

        inference_bundle = {
            "landmarks": self._landmark_result_to_dict(landmark_result),
            "measurements": measurements,
            "spacing": spacing,  # 传递实际使用的 spacing 给 pipeline
        }

        self.logger.info(
            "Completed Ceph inference: %s landmarks detected, %s measurements, spacing=%.4f mm/px",
            len(landmark_result.detected),
            len(measurements),
            spacing,
        )
        return inference_bundle

    def _get_spacing(self, patient_info: Dict[str, Any], landmark_result: LandmarkResult) -> float:
        """
        确定像素间距 (mm/pixel)
        
        优先级：
            1. patient_info 中的 PixelSpacing（从 DICOM metadata 或设备参数）
            2. 使用默认值（⚠️ 警告：可能不准确）
        
        Args:
            patient_info: 患者信息字典
            landmark_result: 关键点检测结果（用于日志记录图像尺寸）
            
        Returns:
            float: Spacing (mm/pixel)
        """
        # 优先使用用户提供的 PixelSpacing
        user_spacing = patient_info.get("PixelSpacing")
        
        if user_spacing is not None:
            spacing = float(user_spacing)
            self.logger.info(f"✅ Using user-provided PixelSpacing: {spacing} mm/pixel")
            return spacing
        
        # 后备方案：使用默认值（并发出警告）
        spacing = self.default_spacing
        
        # 获取图像尺寸用于日志
        orig_shape = landmark_result.orig_shape
        img_info = f"{orig_shape}" if orig_shape else "unknown"
        
        self.logger.warning(
            f"⚠️  PixelSpacing not provided! Using default: {spacing} mm/pixel\n"
            f"    Image size: {img_info}\n"
            f"    ❗ Length measurements may be inaccurate!\n"
            f"    💡 Recommendation: Provide PixelSpacing in patient_info for accurate measurements."
        )
        
        return spacing

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

