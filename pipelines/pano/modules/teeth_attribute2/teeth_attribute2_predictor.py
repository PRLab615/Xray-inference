# 文件名: teeth_attribute2_predictor.py
"""
牙齿属性检测模块 - YOLOv11 检测模型实现
"""
import sys
import logging
import os
import torch
from ultralytics import YOLO
from PIL import Image
import numpy as np
from typing import Dict, Any, List, Optional

# --- 稳健路径设置 ---
current_file_path = os.path.abspath(__file__)
current_dir = os.path.dirname(current_file_path)
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

from tools.weight_fetcher import ensure_weight_file, WeightFetchError
#from pipelines.pano.modules.teeth_attribute2.pre_post import process_teeth_attributes

logger = logging.getLogger(__name__)

class TeethAttribute2Module:
    """
    全景片牙齿属性检测模块（YOLOv11 检测模型实现）
    主要功能：
    - 预测 bbox + class（无分割掩码）
    - 过滤无用标签
    """

    def __init__(
        self,
        *,
        weights_key: Optional[str] = None,
        weights_force_download: bool = False,
        device: Optional[str] = None,
        conf: float = 0.25,
        iou: float = 0.45,
    ):
        self.weights_key = weights_key
        self.weights_force_download = weights_force_download
        self.conf = conf
        self.iou = iou

        if device is None:
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        elif device == "cpu":
            self.device = 'cpu'
        else:
            self.device = f'cuda:{device}' if torch.cuda.is_available() else 'cpu'

        self.weights_path = self._resolve_weights_path()
        self.model = self._load_model()

        # 有用标签与过滤标签
        self.useful_labels = {
            0: 'rct_treated',
            1: 'root_absorption'

        }
        self.filtered_indices = set([2])

    def _resolve_weights_path(self) -> str:
        env_weights = os.getenv("PANO_TEETH_ATTR2_WEIGHTS")
        candidates = [
            ("weights_key", self.weights_key),
            ("env", env_weights),
        ]
        for origin, candidate in candidates:
            if not candidate:
                continue
            if os.path.exists(candidate):
                logger.info(f"Using local weights file: {candidate} (from {origin})")
                return candidate

            # 尝试本地缓存路径
            local_cache_path = os.path.join("cached_weights", candidate)
            if os.path.exists(local_cache_path):
                logger.info(f"Using cached weights file: {local_cache_path} (from {origin})")
                return local_cache_path

            if origin == "weights_key":
                try:
                    downloaded = ensure_weight_file(candidate, force_download=self.weights_force_download)
                    logger.info(f"Downloaded Teeth attribute2 weights from S3 key '{candidate}' to {downloaded}")
                    return downloaded
                except WeightFetchError as e:
                    logger.warning(f"Failed to download from {origin}: {e}")
                    continue
        raise FileNotFoundError(
            "Teeth attribute2 detection model weights not found. "
            "Please configure weights_key in config.yaml."
        )

    def _load_model(self) -> YOLO:
        try:
            logger.info(f"Initializing YOLO model from: {self.weights_path}")
            logger.info(f"CUDA available: {torch.cuda.is_available()}, Target device: {self.device}")
            model = YOLO(self.weights_path)
            logger.info("YOLOv11 Teeth Attribute2 Detection Model initialized successfully.")
            return model
        except Exception as e:
            logger.error(f"Failed to load Teeth attribute2 detection model: {e}")
            raise

    def predict(self, image: Image.Image) -> Dict[str, Any]:
        """
        执行牙齿属性 *检测* 推理（无分割）
        返回：
        - boxes: Nx4
        - attribute_names: 过滤后的 class 名称列表
        """
        if not self.model:
            logger.error("Model not loaded.")
            return {"boxes": [], "attribute_names": [], "original_shape": image.size[::-1]}

        original_shape = image.size[::-1]  # (H, W)
        logger.info("Starting YOLOv11 teeth attribute2 detection inference.")
        try:
            results = self.model.predict(
                source=image,
                conf=self.conf,
                iou=self.iou,
                device=self.device,
                verbose=False,
                save=False,
            )
            if not results:
                logger.warning("No teeth attributes detected.")
                return {"boxes": [], "attribute_names": [], "original_shape": original_shape}

            boxes_xyxy = results[0].boxes.xyxy.cpu().numpy() if results[0].boxes else np.array([]).reshape(0, 4)
            class_indices = results[0].boxes.cls.cpu().numpy() if results[0].boxes else np.array([])
            confidences = results[0].boxes.conf.cpu().numpy() if results[0].boxes else np.array([])

            # 数据一致性检查
            if results[0].boxes:
                n_boxes = len(boxes_xyxy)
                n_classes = len(class_indices)
                n_confs = len(confidences)

                if n_boxes != n_classes or n_boxes != n_confs:
                    logger.warning(f"YOLO output inconsistency detected: boxes={n_boxes}, classes={n_classes}, confidences={n_confs}")
                    # 使用最小长度确保数据一致
                    min_len = min(n_boxes, n_classes, n_confs)
                    boxes_xyxy = boxes_xyxy[:min_len]
                    class_indices = class_indices[:min_len]
                    confidences = confidences[:min_len]

            attribute_names = []
            filtered_boxes = []
            filtered_confidences = []
            for i, (box, cls) in enumerate(zip(boxes_xyxy, class_indices)):
                cls = int(cls)
                if cls not in self.filtered_indices and cls in self.useful_labels:
                    filtered_boxes.append(box)
                    attribute_names.append(self.useful_labels[cls])
                    filtered_confidences.append(confidences[i] if i < len(confidences) else 0.5)

            logger.info(f"Detected {len(filtered_boxes)} useful detections.")
            logger.info(f"Useful attribute names: {attribute_names}")
            logger.info(f"Original image shape: {original_shape}")

            return {
                "boxes": np.array(filtered_boxes),
                "attribute_names": attribute_names,
                "confidences": np.array(filtered_confidences),
                "original_shape": original_shape
            }
        except Exception as e:
            logger.error(f"Teeth attribute2 detection inference failed: {e}")
            raise

