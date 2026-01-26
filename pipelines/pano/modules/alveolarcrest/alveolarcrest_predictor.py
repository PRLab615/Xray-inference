# 文件名: alveolarcrest_predictor.py
"""牙槽骨分割模块 - YOLOv11 实例分割实现"""

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

# 导入统一的权重获取工具
from tools.weight_fetcher import ensure_weight_file, WeightFetchError
from tools.timer import timer

logger = logging.getLogger(__name__)


class AlveolarCrestSegmentationModule:
    """
    全景片牙槽骨分割模块（YOLOv11 实例分割实现），检测牙槽骨掩码。

    权重路径通过 config.yaml 统一配置，不再使用硬编码路径。
    """

    def __init__(
            self,
            *,
            weights_key: Optional[str] = None,
            weights_force_download: bool = False,
            device: Optional[str] = None,
            conf: float = 0.25,
            iou: float = 0.3,
            imgsz: int = 640,
            retina_masks: bool = True,
            agnostic_nms: bool = True,
            max_det: int = 1,
    ):
        """
        初始化牙槽骨分割模块

        Args:
            weights_key: S3 权重路径（从 config.yaml 传入）
            weights_force_download: 是否强制重新下载权重
            device: 推理设备（"0", "cpu" 等）
            conf: 置信度阈值
            iou: NMS IoU 阈值
            imgsz: 推理图像尺寸
            retina_masks: 是否使用高分辨率 mask（更平滑的边缘）
            agnostic_nms: 是否使用类无关 NMS
            max_det: 最大检测数量（默认1，确保只输出最强的一个）
        """
        self.weights_key = weights_key
        self.weights_force_download = weights_force_download
        self.conf = conf
        self.iou = iou
        self.imgsz = imgsz
        self.retina_masks = retina_masks
        self.agnostic_nms = agnostic_nms
        self.max_det = max_det

        # 处理 device 参数
        # config.yaml 中 device: "0" 表示 GPU 0，"cpu" 表示 CPU
        if device is None:
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        elif device == "cpu":
            self.device = 'cpu'
        else:
            # "0", "1" 等数字字符串表示 GPU 索引
            self.device = f'cuda:{device}' if torch.cuda.is_available() else 'cpu'

        self.weights_path = self._resolve_weights_path()
        self.model = self._load_model()

    def _resolve_weights_path(self) -> str:
        """
        解析权重文件路径

        优先级：
            1. 配置的 weights_key（从 config.yaml 传入，可通过 S3 下载）
            2. 环境变量 PANO_ALVEOLARCREST_SEG_WEIGHTS（可选覆盖）
        """
        env_weights = os.getenv("PANO_ALVEOLARCREST_SEG_WEIGHTS")

        candidates = [
            ("weights_key", self.weights_key),
            ("env", env_weights),
        ]

        for origin, candidate in candidates:
            if not candidate:
                continue

            # 如果是本地存在的文件，直接返回
            if os.path.exists(candidate):
                logger.info(f"Using local weights file: {candidate} (from {origin})")
                return candidate

            # 尝试从 S3 下载
            if origin == "weights_key":
                try:
                    downloaded = ensure_weight_file(candidate, force_download=self.weights_force_download)
                    logger.info(f"Downloaded AlveolarCrest weights from S3 key '{candidate}' to {downloaded}")
                    return downloaded
                except WeightFetchError as e:
                    logger.warning(f"Failed to download from {origin}: {e}")
                    continue

        # 所有候选路径都失败
        error_msg = (
            f"AlveolarCrest segmentation model weights not found. "
            f"Please configure weights_key in config.yaml under pipelines.panoramic.modules.alveolarcrest_seg"
        )
        raise FileNotFoundError(error_msg)

    def _load_model(self) -> YOLO:
        """加载 YOLOv11 实例分割模型"""
        try:
            logger.info(f"Initializing AlveolarCrest YOLO model from: {self.weights_path}")
            logger.info(f"CUDA available: {torch.cuda.is_available()}, Target device: {self.device}")
            model = YOLO(self.weights_path)
            if torch.cuda.is_available() and str(self.device).startswith('cuda'):
                try:
                    model.to(self.device)
                    logger.info("AlveolarCrest YOLO model moved to %s", self.device)
                except Exception as exc:
                    logger.warning("Failed to move AlveolarCrest model to %s: %s", self.device, exc)
            logger.info("YOLOv11 AlveolarCrest Segmentation Model initialized successfully.")
            return model
        except Exception as e:
            logger.error(f"Failed to load AlveolarCrest model: {e}")
            raise

    def predict(self, image: Image.Image) -> Dict[str, Any]:
        """
        执行牙槽骨分割推理，返回 mask 和轮廓坐标。

        Args:
            image: PIL Image 对象

        Returns:
            dict: {
                'mask': np.ndarray,  # [H, W] 二值掩码
                'contour': List[List[float]],  # [[x, y], ...] 轮廓坐标
                'confidence': float,  # 置信度
                'bbox': List[float],  # [x, y, w, h] 边界框
                'exists': bool,  # 是否检测到牙槽骨
                'original_shape': tuple  # (H, W) 原始图像尺寸
            }
        """
        if not self.model:
            logger.error("Model not loaded. Skipping prediction.")
            return {"mask": None, "contour": [], "confidence": 0.0, "bbox": [], "exists": False,
                    "original_shape": image.size[::-1]}

        original_shape = image.size[::-1]  # (H, W)
        logger.info("Starting YOLOv11 alveolar crest segmentation inference.")

        try:
            # YOLO 实例分割推理
            with timer.record("alveolarcrest_seg.inference"):
                results = self.model.predict(
                    source=image,
                    conf=self.conf,
                    iou=self.iou,
                    imgsz=self.imgsz,
                    max_det=self.max_det,  # 确保最终只选最强的一个
                    device=self.device,
                    retina_masks=self.retina_masks,
                    agnostic_nms=self.agnostic_nms,
                    verbose=False,
                    save=False,
                )

                if not results or len(results) == 0:
                    logger.warning("No alveolar crest detected.")
                    return {"mask": None, "contour": [], "confidence": 0.0, "bbox": [], "exists": False,
                            "original_shape": original_shape}

            # 结果提取（Post-processing）
            with timer.record("alveolarcrest_seg.post"):
                # 提取 masks（YOLO的masks已经是原始图像尺寸）
                masks = results[0].masks.data.cpu().numpy() if results[0].masks is not None else np.array([])

                if len(masks) == 0:
                    logger.warning("No alveolar crest mask detected.")
                    return {"mask": None, "contour": [], "confidence": 0.0, "bbox": [], "exists": False,
                            "original_shape": original_shape}

                # 只取第一个 mask（模型输出只有一个类别）
                mask = masks[0]  # [H, W]

                # 提取轮廓坐标
                contour = []
                segments = None
                masks_obj = results[0].masks
                if masks_obj is not None and getattr(masks_obj, "xy", None) is not None:
                    xy_data = masks_obj.xy
                    if len(xy_data) > 0:
                        try:
                            poly_arr = np.array(xy_data[0], dtype=float)
                            if poly_arr.ndim == 2 and poly_arr.shape[1] == 2:
                                contour = poly_arr.tolist()
                                logger.info(f"Extracted {len(contour)} contour points from YOLO masks.")
                        except Exception as exc:
                            logger.warning(f"Failed to convert polygon: {exc}")

                # 如果没有轮廓，从 mask 提取
                if not contour:
                    contour = self._extract_contour_from_mask(mask)

                # 提取置信度
                confidences = results[0].boxes.conf.cpu().numpy() if results[0].boxes is not None else np.array([])
                confidence = float(confidences[0]) if len(confidences) > 0 else 0.0

                # 提取 bbox
                boxes = results[0].boxes.xywh.cpu().numpy() if results[0].boxes is not None else np.array([])
                bbox = boxes[0].tolist() if len(boxes) > 0 else []

                logger.info(f"Alveolar crest detected with confidence: {confidence:.2f}")

            return {
                "mask": mask,  # [H, W] binary mask (原始图像尺寸)
                "contour": contour,  # [[x, y], ...] 轮廓坐标（原始图像坐标）
                "confidence": confidence,  # 置信度
                "bbox": bbox,  # [x, y, w, h]
                "exists": True,  # 检测到牙槽骨
                "original_shape": original_shape
            }

        except Exception as e:
            logger.error(f"Alveolar crest segmentation inference failed: {e}")
            raise

    def _extract_contour_from_mask(self, mask: np.ndarray) -> List[List[float]]:
        """
        从 mask 中提取轮廓坐标（降级方案）

        Args:
            mask: [H, W] 二值掩码

        Returns:
            List[List[float]]: [[x, y], ...] 轮廓坐标
        """
        import cv2

        try:
            # 确保 mask 是二值化的 uint8 格式
            if mask.dtype != np.uint8:
                binary_mask = (mask > 0.5).astype(np.uint8)
            else:
                binary_mask = mask

            # 提取轮廓
            contours, _ = cv2.findContours(
                binary_mask,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE
            )

            if contours:
                # 取最大轮廓
                largest_contour = max(contours, key=cv2.contourArea)
                # 多边形近似（减少点数）
                epsilon = 0.005 * cv2.arcLength(largest_contour, True)
                approx_contour = cv2.approxPolyDP(largest_contour, epsilon, True)

                coords = approx_contour.squeeze()
                if coords.ndim == 1:
                    return [[float(coords[0]), float(coords[1])]]
                else:
                    return [[float(pt[0]), float(pt[1])] for pt in coords]

            return []

        except Exception as e:
            logger.warning(f"Failed to extract contour from mask: {e}")
            return []

