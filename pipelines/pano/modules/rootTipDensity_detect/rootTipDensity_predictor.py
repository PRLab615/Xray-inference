# -*- coding: utf-8 -*-
"""
根尖低密度影检测模块 - YOLOv11 实现
用于检测全景片中的根尖低密度影（Low_Density_Lesion）

权重路径通过 config.yaml 统一配置，不再使用硬编码路径。
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

# 导入统一的权重获取工具
from tools.weight_fetcher import ensure_weight_file, WeightFetchError
from tools.timer import timer
from pipelines.pano.modules.rootTipDensity_detect.pre_post import process_detections

logger = logging.getLogger(__name__)


class RootTipDensityPredictor:
    """
    全景片根尖低密度影检测模块（YOLOv11实现）
    
    权重路径通过 config.yaml 统一配置，不再使用硬编码路径。
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
        """
        初始化根尖低密度影检测模块
        
        Args:
            weights_key: S3 权重路径（从 config.yaml 传入）
            weights_force_download: 是否强制重新下载权重
            device: 推理设备（"0", "cpu" 等）
            conf: 置信度阈值
            iou: NMS IoU 阈值
        """
        self.weights_key = weights_key
        self.weights_force_download = weights_force_download
        self.conf = conf
        self.iou = iou
        
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
        self.model: YOLO = self._load_model()

    def _resolve_weights_path(self) -> str:
        """
        解析权重文件路径
        
        优先级：
            1. 配置的 weights_key（从 config.yaml 传入，可通过 S3 下载）
            2. 环境变量 PANO_ROOT_TIP_DENSITY_WEIGHTS（可选覆盖）
        """
        env_weights = os.getenv("PANO_ROOT_TIP_DENSITY_WEIGHTS")
        
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
                    logger.info(f"Downloaded RootTipDensity weights from S3 key '{candidate}' to {downloaded}")
                    return downloaded
                except WeightFetchError as e:
                    logger.warning(f"Failed to download from {origin}: {e}")
                    continue
        
        # 所有候选路径都失败
        error_msg = (
            f"RootTipDensity detection model weights not found. "
            f"Please configure weights_key in config.yaml under pipelines.panoramic.modules.rootTipDensity_detect"
        )
        raise FileNotFoundError(error_msg)

    def _load_model(self) -> YOLO:
        """加载 YOLOv11 模型并预热"""
        try:
            logger.info(f"Initializing RootTipDensity YOLO model from: {self.weights_path}")
            logger.info(f"CUDA available: {torch.cuda.is_available()}, Target device: {self.device}")
            # 显式指定 task='detect'，避免 ONNX 模型加载时的警告
            model = YOLO(self.weights_path, task='detect')
            
            # 显式将模型移动到目标设备（GPU），实现预加载
            if torch.cuda.is_available() and str(self.device).startswith('cuda'):
                try:
                    model.to(self.device)
                    logger.info("RootTipDensity YOLO model moved to %s", self.device)
                except Exception as exc:
                    logger.warning("Failed to move RootTipDensity model to %s: %s", self.device, exc)
            
            # 预热推理：执行一次 dummy 推理，确保模型权重完全加载到 GPU 并完成 CUDA kernel 编译
            # 这对于 ONNX 模型特别重要，因为 YOLO 可能在第一次 predict 时才真正加载 ONNX Runtime
            logger.info("Warming up RootTipDensity model (preloading weights to GPU)...")
            try:
                # 创建一个小的 dummy 图像用于预热（ONNX 模型需要 1024x1024 输入）
                dummy_image = np.zeros((1024, 1024, 3), dtype=np.uint8)
                with torch.no_grad():
                    _ = model.predict(
                        source=dummy_image,
                        device=self.device,
                        verbose=False,
                        conf=self.conf,
                        iou=self.iou
                    )
                logger.info("RootTipDensity model warmup completed successfully.")
            except Exception as warmup_exc:
                logger.warning(f"Model warmup failed (non-critical): {warmup_exc}")
                # 预热失败不影响模型使用，继续初始化
            
            logger.info("YOLOv11 RootTipDensity Detection Model initialized successfully.")
            return model
        except Exception as e:
            logger.error(f"Failed to load RootTipDensity model: {e}")
            raise

    @torch.no_grad()
    def predict(self, image: Image.Image) -> Dict[str, Any]:
        """
        执行根尖低密度影检测推理
        
        Args:
            image: PIL Image 对象
            
        Returns:
            dict: {
                "density_boxes": [{"box": [x1, y1, x2, y2], "confidence": float, "quadrant": int}, ...],
                "quadrant_counts": {1: int, 2: int, 3: int, 4: int}
            }
        """
        if not self.model:
            logger.error("Model is not loaded. Skipping prediction.")
            return {"density_boxes": [], "quadrant_counts": {1: 0, 2: 0, 3: 0, 4: 0}}

        original_shape = image.size[::-1]  # (H, W)
        logger.info("Starting YOLOv11 rootTipDensity detection inference.")

        try:
            # YOLO 推理（ONNX 模型需要 1024x1024 输入）
            with timer.record("rootTipDensity_detect.inference"):
                results = self.model.predict(
                    imgsz=1024,
                    source=image,
                    conf=self.conf,
                    iou=self.iou,
                    device=self.device,
                    verbose=False
                )

                if not results or len(results) == 0:
                    logger.warning("YOLO inference returned no results.")
                    return {"density_boxes": [], "quadrant_counts": {1: 0, 2: 0, 3: 0, 4: 0}}

                yolo_predictions_tensor = results[0].boxes.data.cpu().numpy()

        except Exception as e:
            logger.error(f"YOLOv11 rootTipDensity detection inference failed: {e}")
            raise

        # 后处理
        with timer.record("rootTipDensity_detect.post"):
            final_results: Dict[str, Any] = process_detections(
                predictions=yolo_predictions_tensor,
                original_img_shape=original_shape,
            )

        return final_results
