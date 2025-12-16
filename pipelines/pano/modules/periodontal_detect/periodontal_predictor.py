# -*- coding: utf-8 -*-
"""
牙周吸收检测模块 - 关键点检测实现
接收牙齿分割结果，进行象限截取，然后进行关键点检测和牙周吸收分析
"""
import sys
import logging
import os
import torch
from ultralytics import YOLO
import cv2
import numpy as np
from typing import Dict, Any, List, Optional
from PIL import Image

# --- 稳健路径设置 ---
current_file_path = os.path.abspath(__file__)
current_dir = os.path.dirname(current_file_path)
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

# 导入统一的权重获取工具
from tools.weight_fetcher import ensure_weight_file, WeightFetchError
from tools.timer import timer
from pipelines.pano.modules.periodontal_detect.pre_post import (
    process_panoramic_segmentation,
    analyze_absorption,
)

logger = logging.getLogger(__name__)


class PeriodontalPredictor:
    """
    牙周吸收检测模块（关键点检测实现）
    
    工作流程：
    1. 接收牙齿分割结果（从 teeth_seg 模块）
    2. 按象限截取图像（前处理）
    3. 对每个象限进行关键点检测
    4. 计算牙周吸收（后处理）
    
    权重路径通过 config.yaml 统一配置，使用 weight_fetcher 获取。
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
        初始化牙周吸收检测模块
        
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
            2. 环境变量 PERIODONTAL_WEIGHTS（可选覆盖）
        """
        env_weights = os.getenv("PERIODONTAL_WEIGHTS")
        
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
                    logger.info(f"Downloaded Periodontal weights from S3 key '{candidate}' to {downloaded}")
                    return downloaded
                except WeightFetchError as e:
                    logger.warning(f"Failed to download from {origin}: {e}")
                    continue
        
        # 所有候选路径都失败
        error_msg = (
            f"Periodontal detection model weights not found. "
            f"Please configure weights_key in config.yaml under pipelines.panoramic.modules.periodontal_detect"
        )
        raise FileNotFoundError(error_msg)

    def _load_model(self) -> YOLO:
        """加载 YOLOv11 关键点检测模型"""
        try:
            logger.info(f"Initializing Periodontal YOLO model from: {self.weights_path}")
            logger.info(f"CUDA available: {torch.cuda.is_available()}, Target device: {self.device}")
            model = YOLO(self.weights_path)
            if torch.cuda.is_available() and str(self.device).startswith('cuda'):
                try:
                    model.to(self.device)
                    logger.info("Periodontal YOLO model moved to %s", self.device)
                except Exception as exc:
                    logger.warning("Failed to move Periodontal model to %s: %s", self.device, exc)
            logger.info("YOLOv11 Periodontal Detection Model initialized successfully.")
            return model
        except FileNotFoundError:
            # 文件不存在，直接抛出
            raise
        except WeightFetchError:
            # 权重获取错误，直接抛出
            raise
        except Exception as e:
            # 其他加载错误（如文件格式错误、模型损坏等），转换为 FileNotFoundError
            # 这样 pipeline 的异常处理可以捕获并进入 mock 模式
            logger.error(f"Failed to load Periodontal model from {self.weights_path}: {e}")
            raise FileNotFoundError(
                f"Periodontal detection model file exists but failed to load: {e}. "
                f"Please check if the model file is valid."
            ) from e

    def predict(
        self,
        image_path: str,
        teeth_seg_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行牙周吸收检测
        
        Args:
            image_path: 全景片图像路径
            teeth_seg_results: 牙齿分割模块的结果，包含：
                - masks: [N, H, W] 牙齿分割mask数组
                - class_names: [N] 标签列表，如 ["tooth-11", "tooth-12", ...]
                - original_shape: (H, W) 原始图像尺寸
        
        Returns:
            dict: 包含各象限的牙周吸收分析结果
                {
                    "quadrant_1": [...],  # 该象限的牙齿吸收结果列表
                    "quadrant_2": [...],
                    "quadrant_3": [...],
                    "quadrant_4": [...],
                }
        """
        if not self.model:
            logger.error("Model not loaded. Skipping prediction.")
            return {}

        # 加载原始图像
        image = cv2.imread(image_path)
        if image is None:
            logger.error(f"Failed to load image: {image_path}")
            return {}

        # 提取牙齿分割结果
        masks = teeth_seg_results.get("masks", np.array([]))
        labels = teeth_seg_results.get("class_names", [])
        original_shape = teeth_seg_results.get("original_shape", image.shape[:2])
        
        if len(masks) == 0 or len(labels) == 0:
            logger.warning("No teeth detected in segmentation results, skipping periodontal analysis")
            return {}

        logger.info(f"Starting periodontal detection. Image: {image_path}")
        logger.info(f"  Detected {len(labels)} teeth, image shape: {image.shape}")

        # 前处理：按象限截取
        with timer.record("periodontal.preprocess"):
            quadrant_data = process_panoramic_segmentation(
                image, masks, labels, original_shape
            )

        # 对每个象限进行关键点检测和分析
        all_absorption_results = {}
        
        for quadrant in [1, 2, 3, 4]:
            crop_img, crop_mask, tooth_ids, has_deciduous = quadrant_data.get(quadrant, (None, None, [], False))
            
            # 如果包含乳牙，跳过关键点检测，直接标记为正常
            if has_deciduous:
                logger.info(f"  Quadrant {quadrant}: Contains deciduous teeth, marking as normal")
                # 为该象限的期望牙齿创建正常结果
                from pipelines.pano.modules.periodontal_detect.pre_post import QUADRANT_TEETH
                expected_teeth = QUADRANT_TEETH.get(quadrant, [])
                deciduous_results = []
                for tooth_id in expected_teeth:
                    deciduous_results.append({
                        "tooth_id": tooth_id,
                        "cej_point": None,
                        "apex_point": None,
                        "boneline_point": None,
                        "absorption_ratio": 0.0,
                        "severity": "正常",
                        "confidence": 1.0,  # 乳牙标记为正常，置信度设为1.0
                        "distance_cej_boneline": None,
                        "distance_cej_apex": None,
                    })
                all_absorption_results[f"quadrant_{quadrant}"] = deciduous_results
                continue
            
            if crop_img is None:
                logger.warning(f"  Quadrant {quadrant}: No valid crop image, skipping")
                all_absorption_results[f"quadrant_{quadrant}"] = []
                continue

            logger.info(f"  Processing quadrant {quadrant}...")
            logger.info(f"    Found {len(tooth_ids)} teeth: {tooth_ids}")

            # 关键点检测
            with timer.record(f"periodontal.inference.quadrant_{quadrant}"):
                pose_results = self.model.predict(
                    crop_img,
                    conf=self.conf,
                    iou=self.iou,
                    device=self.device,
                    verbose=False,
                    save=False,
                )

            num_detections = len(pose_results[0].boxes) if pose_results[0].boxes is not None else 0
            logger.info(f"    Detected {num_detections} tooth instances with keypoints")

            # 后处理：分析牙周吸收
            with timer.record(f"periodontal.postprocess.quadrant_{quadrant}"):
                absorption_results = analyze_absorption(pose_results, tooth_ids)
                all_absorption_results[f"quadrant_{quadrant}"] = absorption_results

            # 输出结果（只输出轻中重度，隐藏正常）
            for result in absorption_results:
                tooth_id = result["tooth_id"]
                severity = result["severity"]
                if severity != "正常":
                    ratio = result["absorption_ratio"]
                    logger.info(f"    Tooth {tooth_id}: {severity} absorption (ratio: {ratio:.3f})")

        logger.info("Periodontal detection completed")
        return all_absorption_results

