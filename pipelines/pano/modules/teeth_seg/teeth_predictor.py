# 文件名: teeth_predictor.py
import sys
import logging
import os
import torch
from ultralytics import YOLO
from PIL import Image
import numpy as np
from typing import Dict, Any, List

# --- 稳健路径设置 ---
current_file_path = os.path.abspath(__file__)
current_dir = os.path.dirname(current_file_path)
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

# 导入
from tools.load_weight import get_s3_client, S3_BUCKET_NAME, LOCAL_WEIGHTS_DIR, load_model_weights
from pipelines.pano.modules.teeth_seg.pre_post import process_teeth_masks  # 后处理

logger = logging.getLogger(__name__)

# YOLO 模型 S3 路径 (YOLOv11 实例分割模型)
YOLO_S3_PATH = "weights/panoramic/1116_teeth_seg.pt"  # 假设模型路径


class TeethSegmentationModule:
    """
    全景片牙齿分割模块（YOLOv11 实例分割实现），检测牙齿序号掩码并后处理缺牙/智齿/乳牙。
    """

    def __init__(self, device: str = None):
        """
        初始化牙齿分割模块，加载权重。
        """
        if device is None:
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        else:
            self.device = device

        self.model = self._load_model()

    def _load_model(self) -> YOLO:
        """
        加载 YOLOv11 实例分割模型。
        """
        # 触发 MinIO 下载
        weights_state_dict = load_model_weights(YOLO_S3_PATH, device='cpu', force_download=False)
        local_weight_path = os.path.join(LOCAL_WEIGHTS_DIR, YOLO_S3_PATH)

        if weights_state_dict is None or not os.path.exists(local_weight_path):
            logger.error(f"Teeth segmentation weights not found: {local_weight_path}")
            raise FileNotFoundError(f"Teeth model file not found after download.")

        try:
            logger.info(f"Initializing Teeth YOLO model from: {local_weight_path} on {self.device}")
            model = YOLO(local_weight_path)
            model.to(self.device)
            model.eval()
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
            results = self.model.predict(
                source=image,
                conf=0.25,  # 置信度阈值
                iou=0.45,   # NMS IoU
                device=self.device,
                verbose=False,
                save=False,  # 不保存图像
                # 可选: 过滤特定类，如果模型有类 ID
                # classes=range(1, 49)  # 假设 1-48 为恒牙，额外乳牙类
            )

            if not results or len(results) == 0:
                logger.warning("No teeth detected.")
                return {"masks": [], "class_names": [], "original_shape": original_shape}

            # 提取 masks 和 class names (YOLO 实例分割输出)
            # masks: [N, H, W] binary masks (normalized to [0,1])
            masks = results[0].masks.data.cpu().numpy() if results[0].masks is not None else np.array([])

            # classes: class indices [N]
            class_indices = results[0].boxes.cls.cpu().numpy() if results[0].boxes is not None else np.array([])

            # class names: 从模型 names 字典获取 (假设 names = {0: 'tooth-11', 1: 'tooth-12', ...})
            class_names = [self.model.names[int(idx)] for idx in class_indices] if len(class_indices) > 0 else []

            logger.info(f"Detected {len(class_names)} teeth segments.")
            return {
                "masks": masks,  # [N, H, W] binary masks
                "class_names": class_names,  # [N] strings like "tooth-11"
                "original_shape": original_shape
            }

        except Exception as e:
            logger.error(f"Teeth segmentation inference failed: {e}")
            raise


def process_teeth_results(raw_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    调用后处理，生成缺牙/智齿/乳牙报告。
    """
    return process_teeth_masks(raw_results["masks"], raw_results["class_names"], raw_results["original_shape"])


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