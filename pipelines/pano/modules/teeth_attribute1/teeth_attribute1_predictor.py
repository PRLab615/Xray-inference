# 文件名: teeth_attribute1_predictor.py
"""牙齿属性分割模块 - YOLOv11 实例分割实现"""

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
from pipelines.pano.modules.teeth_attribute1.pre_post import process_teeth_attributes  # 后处理

logger = logging.getLogger(__name__)


class TeethAttributeModule:
    """
    全景片牙齿属性分割模块（YOLOv11 实例分割实现），检测牙齿属性掩码并后处理有用属性。

    权重路径通过 config.yaml 统一配置，不再使用硬编码路径。
    有用标签: 0-restored_tooth, 1-residual_root, 2-residual_crown, 4-carious_lesion,
              5-embedded_tooth, 10-retained_primary_tooth, 11-to_be_erupted, 12-tooth_germ
    过滤标签: 3-area (pathology), 6-impacted, 7-implant (pathology), 8-not_visible, 9-periodontal (pathology)
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
        初始化牙齿属性分割模块

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
        self.model = self._load_model()

        # 定义有用标签索引和名称映射（过滤掉 3,6,7,8,9）
        self.useful_labels = {
            0: 'restored_tooth',
            1: 'residual_root',
            2: 'residual_crown',
            4: 'carious_lesion',
            5: 'embedded_tooth',
            10: 'retained_primary_tooth',
            11: 'to_be_erupted',
            12: 'tooth_germ'
        }
        self.filtered_indices = set([3, 6, 7, 8, 9])  # 过滤标签

    def _resolve_weights_path(self) -> str:
        """
        解析权重文件路径

        优先级：
            1. 配置的 weights_key（从 config.yaml 传入，可通过 S3 下载）
            2. 环境变量 PANO_TEETH_ATTR_WEIGHTS（可选覆盖）
        """
        env_weights = os.getenv("PANO_TEETH_ATTR_WEIGHTS")

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
                    logger.info(f"Downloaded Teeth attribute weights from S3 key '{candidate}' to {downloaded}")
                    return downloaded
                except WeightFetchError as e:
                    logger.warning(f"Failed to download from {origin}: {e}")
                    continue

        # 所有候选路径都失败
        error_msg = (
            f"Teeth attribute segmentation model weights not found. "
            f"Please configure weights_key in config.yaml under pipelines.panoramic.modules.teeth_attr"
        )
        raise FileNotFoundError(error_msg)

    def _load_model(self) -> YOLO:
        """加载 YOLOv11 实例分割模型"""
        try:
            logger.info(f"Initializing Teeth Attribute YOLO model from: {self.weights_path}")
            logger.info(f"CUDA available: {torch.cuda.is_available()}, Target device: {self.device}")
            model = YOLO(self.weights_path)
            # YOLO 模型不需要手动调用 .to()，在 predict 时指定 device 即可
            logger.info("YOLOv11 Teeth Attribute Segmentation Model initialized successfully.")
            return model
        except Exception as e:
            logger.error(f"Failed to load Teeth attribute model: {e}")
            raise

    def predict(self, image: Image.Image) -> Dict[str, Any]:
        """
        执行牙齿属性分割推理，返回原始 masks 和 attribute names（过滤无用标签）。
        """
        if not self.model:
            logger.error("Model not loaded. Skipping prediction.")
            return {"masks": [], "attribute_names": [], "original_shape": image.size[::-1]}

        original_shape = image.size[::-1]  # (H, W)
        logger.info("Starting YOLOv11 teeth attribute segmentation inference.")

        try:
            results = self.model.predict(
                source=image,
                conf=self.conf,
                iou=self.iou,
                device=self.device,
                verbose=False,
                save=False,
            )

            if not results or len(results) == 0:
                logger.warning("No teeth attributes detected.")
                return {"masks": [], "attribute_names": [], "original_shape": original_shape}

            # 提取 masks 和 class indices (YOLO 实例分割输出)
            # masks: [N, H, W] binary masks (normalized to [0,1])
            masks = results[0].masks.data.cpu().numpy() if results[0].masks is not None else np.array([])

            # classes: class indices [N]
            class_indices = results[0].boxes.cls.cpu().numpy() if results[0].boxes is not None else np.array([])

            # 过滤无用标签并映射到名称
            filtered_indices = []
            attribute_names = []
            for idx in class_indices:
                int_idx = int(idx)
                if int_idx not in self.filtered_indices and int_idx in self.useful_labels:
                    filtered_indices.append(int_idx)
                    attribute_names.append(self.useful_labels[int_idx])

            # 相应过滤 masks（假设 masks 顺序与 class_indices 对应）
            if len(masks) > 0 and len(filtered_indices) > 0:
                # 简单过滤：重新索引 masks 到有用部分（实际中可能需根据 boxes 索引）
                # 这里假设顺序一致；生产中可优化为 masks[keep_mask] where keep_mask = [i for i, c in enumerate(class_indices) if int(c) not in filtered]
                keep_mask = np.array(
                    [int(c) not in self.filtered_indices and int(c) in self.useful_labels for c in class_indices])
                masks = masks[keep_mask]
            logger.info(f"Detected {len(masks)} useful masks.")
            logger.info(f"Detected useful attribute names: {attribute_names}")
            logger.info(f"Original image shape: {original_shape}")
            logger.info(f"Detected {attribute_names} useful attribute_names attributes.")
            logger.info(f"Detected {original_shape} useful original_shape attributes.")
            return {
                "masks": masks,  # [N_filtered, H, W] binary masks
                "attribute_names": attribute_names,  # [N_filtered] strings like "restored_tooth"
                "original_shape": original_shape
            }

        except Exception as e:
            logger.error(f"Teeth attribute segmentation inference failed: {e}")
            raise


def process_teeth_attribute_results(raw_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    调用后处理，生成牙齿属性报告，并保留原始掩码数据。
    """
    processed_results = process_teeth_attributes(
        raw_results["masks"],
        raw_results["attribute_names"],
        raw_results["original_shape"]
    )

    # 保留原始掩码数据，以便后续生成 ToothAttributeAnalysis
    processed_results["raw_masks"] = raw_results["masks"]
    processed_results["original_shape"] = raw_results["original_shape"]

    return processed_results


"""
if __name__ == "__main__":
    # 示例使用
    sample_image_path = '/app/code/Xray-inference/2.jpg'  # 修改为实际路径
    if not os.path.exists(sample_image_path):
        # 创建测试图像
        test_img = Image.new('RGB', (1000, 800), color='gray')
        test_img.save(sample_image_path)
        print(f"Created test image: {sample_image_path}")

    try:
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"Using device: {device}")
        detector = TeethAttributeModule(device=device)
        img = Image.open(sample_image_path).convert('RGB')
        print(f"Image size: {img.size}")

        raw_results = detector.predict(img)
        final_report = process_teeth_attribute_results(raw_results)

        print("Teeth Attribute Segmentation Report:")
        import json
        print(json.dumps(final_report, indent=4, ensure_ascii=False))



    except Exception as e:
        print(f"Error: {e}")
        logger.error(f"Main error: {e}")
"""
