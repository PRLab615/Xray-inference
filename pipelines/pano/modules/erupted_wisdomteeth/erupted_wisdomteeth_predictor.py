# 文件名: erupted_predictor.py
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

logger = logging.getLogger(__name__)

class EruptedModule:
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
            0: 'erupted'  # 已萌出
        }
        self.filtered_indices = set()  # 假设新模型仅包含有用标签，无需过滤

    def _resolve_weights_path(self) -> str:
        env_weights = os.getenv("PANO_ERUPTED_WEIGHTS")
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
            if origin == "weights_key":
                try:
                    downloaded = ensure_weight_file(candidate, force_download=self.weights_force_download)
                    logger.info(f"Downloaded erupted weights from S3 key '{candidate}' to {downloaded}")
                    return downloaded
                except WeightFetchError as e:
                    logger.warning(f"Failed to download from {origin}: {e}")
                    continue
        raise FileNotFoundError(
            "Erupted detection model weights not found. "
            "Please configure weights_key in config.yaml."
        )

    def _load_model(self) -> YOLO:
        try:
            logger.info(f"Initializing YOLO model from: {self.weights_path}")
            logger.info(f"CUDA available: {torch.cuda.is_available()}, Target device: {self.device}")
            model = YOLO(self.weights_path)
            logger.info("YOLOv11 Erupted Detection Model initialized successfully.")
            return model
        except Exception as e:
            logger.error(f"Failed to load erupted detection model: {e}")
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
        logger.info("Starting YOLOv11 erupted detection inference.")
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

            boxes_xyxy = results[0].boxes.xyxy.cpu().numpy() if results[0].boxes else np.array([])
            class_indices = results[0].boxes.cls.cpu().numpy() if results[0].boxes else np.array([])

            attribute_names = []
            filtered_boxes = []
            for box, cls in zip(boxes_xyxy, class_indices):
                cls = int(cls)
                if cls not in self.filtered_indices and cls in self.useful_labels:
                    filtered_boxes.append(box)
                    attribute_names.append(self.useful_labels[cls])

            logger.info(f"Detected {len(filtered_boxes)} useful detections.")
            logger.info(f"Useful attribute names: {attribute_names}")
            logger.info(f"Original image shape: {original_shape}")

            return {
                "boxes": np.array(filtered_boxes),
                "attribute_names": attribute_names,
                "original_shape": original_shape
            }
        except Exception as e:
            logger.error(f"Erupted detection inference failed: {e}")
            raise
"""
if __name__ == "__main__":
    # 示例使用
    sample_image_path = '/app/code/x/r.png'  # 修改为实际路径
    if not os.path.exists(sample_image_path):
        # 创建测试图像
        test_img = Image.new('RGB', (1000, 800), color='gray')
        test_img.save(sample_image_path)
        print(f"Created test image: {sample_image_path}")
    try:
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"Using device: {device}")
        detector = EruptedModule(device=device)
        img = Image.open(sample_image_path).convert('RGB')
        print(f"Image size: {img.size}")
        raw_results = detector.predict(img)
        print("Erupted Detection Results:")
        import json
        print(json.dumps(raw_results, indent=4, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}")
        logger.error(f"Main error: {e}")
"""