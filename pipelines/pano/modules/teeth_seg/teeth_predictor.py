# 文件名: teeth_predictor.py
"""牙齿分割模块 - YOLOv11 实例分割实现"""

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
from pipelines.pano.modules.teeth_seg.pre_post import process_teeth_masks  # 后处理

logger = logging.getLogger(__name__)


class TeethSegmentationModule:
    """
    全景片牙齿分割模块（YOLOv11 实例分割实现），检测牙齿序号掩码并后处理缺牙/智齿/乳牙。
    
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
        初始化牙齿分割模块
        
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

    def _resolve_weights_path(self) -> str:
        """
        解析权重文件路径
        
        优先级：
            1. 配置的 weights_key（从 config.yaml 传入，可通过 S3 下载）
            2. 环境变量 PANO_TEETH_SEG_WEIGHTS（可选覆盖）
        """
        env_weights = os.getenv("PANO_TEETH_SEG_WEIGHTS")
        
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
                    logger.info(f"Downloaded Teeth weights from S3 key '{candidate}' to {downloaded}")
                    return downloaded
                except WeightFetchError as e:
                    logger.warning(f"Failed to download from {origin}: {e}")
                    continue
        
        # 所有候选路径都失败
        error_msg = (
            f"Teeth segmentation model weights not found. "
            f"Please configure weights_key in config.yaml under pipelines.panoramic.modules.teeth_seg"
        )
        raise FileNotFoundError(error_msg)

    def _load_model(self) -> YOLO:
        """加载 YOLOv11 实例分割模型"""
        try:
            logger.info(f"Initializing Teeth YOLO model from: {self.weights_path}")
            logger.info(f"CUDA available: {torch.cuda.is_available()}, Target device: {self.device}")
            model = YOLO(self.weights_path)
            if torch.cuda.is_available() and str(self.device).startswith('cuda'):
                try:
                    model.to(self.device)
                    logger.info("Teeth YOLO model moved to %s", self.device)
                except Exception as exc:
                    logger.warning("Failed to move Teeth model to %s: %s", self.device, exc)
            logger.info("YOLOv11 Teeth Segmentation Model initialized successfully.")
            return model
        except Exception as e:
            logger.error(f"Failed to load Teeth model: {e}")
            raise

    def predict(self, image: Image.Image) -> Dict[str, Any]:
        """
        执行牙齿分割推理，返回原始 masks 和 class names。
        """
        if not self.model:
            logger.error("Model not loaded. Skipping prediction.")
            return {"masks": [], "class_names": [], "original_shape": image.size[::-1]}

        original_shape = image.size[::-1]  # (H, W)
        logger.info("Starting YOLOv11 teeth segmentation inference.")

        try:
            # YOLO 实例分割推理
            with timer.record("teeth_seg.inference"):
                results = self.model.predict(
                    source=image,
                    conf=self.conf,
                    iou=self.iou,
                    device=self.device,
                    verbose=False,
                    save=False,
                )

                if not results or len(results) == 0:
                    logger.warning("No teeth detected.")
                    return {"masks": [], "class_names": [], "original_shape": original_shape}

            # 结果提取（Post-processing）
            with timer.record("teeth_seg.post"):
                # 提取 masks 和 class names (YOLO 实例分割输出)
                # masks: [N, H, W] binary masks (normalized to [0,1])
                # 注意：YOLO的masks已经是原始图像尺寸，不需要resize
                masks = results[0].masks.data.cpu().numpy() if results[0].masks is not None else np.array([])

                segments: Optional[List[np.ndarray]] = None
                masks_obj = results[0].masks
                if masks_obj is not None and getattr(masks_obj, "xy", None) is not None:
                    xy_data = masks_obj.xy
                    segments = []
                    for idx, poly in enumerate(xy_data):
                        try:
                            poly_arr = np.array(poly, dtype=float)
                            if poly_arr.ndim == 2 and poly_arr.shape[1] == 2:
                                segments.append(poly_arr)
                            else:
                                logger.warning(f"Polygon {idx} has unexpected shape {poly_arr.shape}, skipping")
                        except Exception as exc:
                            logger.warning(f"Failed to convert polygon {idx}: {exc}")
                    if not segments:
                        segments = None
                if segments is not None:
                    logger.info(f"Extracted {len(segments)} tooth polygons from YOLO masks.")
                else:
                    logger.warning("No segmentation polygons extracted from YOLO masks.")

                # classes: class indices [N]
                class_indices = results[0].boxes.cls.cpu().numpy() if results[0].boxes is not None else np.array([])

                # class names: 从模型 names 字典获取 (假设 names = {0: 'tooth-11', 1: 'tooth-12', ...})
                class_names = [self.model.names[int(idx)] for idx in class_indices] if len(class_indices) > 0 else []

                logger.info(f"Detected {len(class_names)} teeth segments.")

            return {
                "masks": masks,  # [N, H, W] binary masks (已经是原始图像尺寸)
                "segments": segments,  # [N, num_points, 2] 多边形坐标（原始图像坐标）
                "class_names": class_names,  # [N] strings like "tooth-11"
                "original_shape": original_shape
            }

        except Exception as e:
            logger.error(f"Teeth segmentation inference failed: {e}")
            raise


def process_teeth_results(raw_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    调用后处理，生成缺牙/智齿/乳牙报告，并保留原始掩码数据和segments。
    """
    processed_results = process_teeth_masks(
        raw_results["masks"], 
        raw_results["class_names"], 
        raw_results["original_shape"]
    )
    
    # 保留原始掩码数据和segments，以便后续生成 ToothAnalysis
    processed_results["raw_masks"] = raw_results["masks"]
    processed_results["segments"] = raw_results.get("segments", None)  # 多边形坐标
    processed_results["original_shape"] = raw_results["original_shape"]
    
    return processed_results

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
        detector = TeethSegmentationModule(device=device)
        img = Image.open(sample_image_path).convert('RGB')
        print(f"Image size: {img.size}")

        raw_results = detector.predict(img)
        final_report = process_teeth_results(raw_results)

        print("Teeth Segmentation Report:")
        import json
        print(json.dumps(final_report, indent=4, ensure_ascii=False))



    except Exception as e:
        print(f"Error: {e}")
        logger.error(f"Main error: {e}")
"""