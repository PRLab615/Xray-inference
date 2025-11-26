# predictor.py
"""种植体检测模块 - YOLOv11 实现"""

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
from pipelines.pano.modules.implant_detect.pre_post import process_detections

logger = logging.getLogger(__name__)


class ImplantDetectionModule:
    """
    全景片植入物检测模块（YOLOv11实现）
    
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
        初始化种植体检测模块
        
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
            2. 环境变量 PANO_IMPLANT_DETECT_WEIGHTS（可选覆盖）
        """
        env_weights = os.getenv("PANO_IMPLANT_DETECT_WEIGHTS")
        
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
                    logger.info(f"Downloaded Implant weights from S3 key '{candidate}' to {downloaded}")
                    return downloaded
                except WeightFetchError as e:
                    logger.warning(f"Failed to download from {origin}: {e}")
                    continue
        
        # 所有候选路径都失败
        error_msg = (
            f"Implant detection model weights not found. "
            f"Please configure weights_key in config.yaml under pipelines.panoramic.modules.implant_detect"
        )
        raise FileNotFoundError(error_msg)

    def _load_model(self) -> YOLO:
        """加载 YOLOv11 模型"""
        try:
            logger.info(f"Initializing Implant YOLO model from: {self.weights_path}")
            logger.info(f"CUDA available: {torch.cuda.is_available()}, Target device: {self.device}")
            model = YOLO(self.weights_path)
            # YOLO 模型不需要手动调用 .to()，在 predict 时指定 device 即可
            logger.info("YOLOv11 Implant Detection Model initialized successfully.")
            return model
        except Exception as e:
            logger.error(f"Failed to load Implant model: {e}")
            raise

    @torch.no_grad()
    def predict(self, image: Image.Image) -> Dict[str, Any]:

        if not self.model:
            logger.error("Model is not loaded. Skipping prediction.")
            return {"implant_boxes": [], "quadrant_counts": {1: 0, 2: 0, 3: 0, 4: 0}}

        original_shape = image.size[::-1]
        logger.info("Starting YOLOv11 implant detection inference.")

        try:
            # YOLO 推理
            with timer.record("implant_detect.inference"):
                results = self.model.predict(
                    imgsz=640,
                    source=image,
                    conf=self.conf,
                    iou=self.iou,
                    device=self.device,
                    verbose=False
                )

                if not results or len(results) == 0:
                    logger.warning("YOLO inference returned no results.")
                    return {"implant_boxes": [], "quadrant_counts": {1: 0, 2: 0, 3: 0, 4: 0}}

                yolo_predictions_tensor = results[0].boxes.data.cpu().numpy()

        except Exception as e:
            logger.error(f"YOLOv11 implant detection inference failed: {e}")
            raise

        # 后处理
        with timer.record("implant_detect.post"):
            final_results: Dict[str, Any] = process_detections(
                predictions=yolo_predictions_tensor,
                original_img_shape=original_shape,
            )

        return final_results

"""  
if __name__ == "__main__":
    # -------------------- 示例使用 --------------------

    # 示例路径，请修改为实际图片文件
    # **重要**: 如果您在 Linux/Mac 上，路径可能是 /path/to/1.jpg
    # 如果在 Windows 上，路径可能是 C:\\Users\\user\\Desktop\\1.jpg
    sample_image_path = os.path.join(current_dir, "/app/code/x/3.jpg")

    # 尝试创建一个空的图片用于测试，以防用户未提供
    if not os.path.exists(sample_image_path):
        try:
            Image.new('RGB', (1000, 800), color='white').save(sample_image_path)
            print(f"✅ 警告: 未找到 {sample_image_path}，已创建一个 1000x800 的空白图片用于测试。")
        except Exception as e:
            print(f"❌ 错误: 无法创建测试图片。请手动提供有效图片路径。错误: {e}")
            sys.exit(1)

    print("\n--- 启动 ImplantDetectionModule 测试 ---")

    try:
        # 检测设备
        device_to_use = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"🚀 使用设备: {device_to_use}")

        # 实例化模块 (会触发模型加载和 mock 权重文件创建)
        detector = ImplantDetectionModule(device=device_to_use)

        # 加载图片
        img = Image.open(sample_image_path).convert('RGB')
        print(f"🖼️  图片尺寸 (W x H): {img.size[0]} x {img.size[1]}")

        # 执行预测
        print("\n--- 执行预测 (YOLOv11 推理) ---")
        results = detector.predict(img)

        # 输出结果
        print("\n--- 最终检测结果 ---")
        import json

        print(json.dumps(results, indent=4))

        # 总结
        print("-" * 50)
        print(f"总检测到的植入物数量: {len(results['implant_boxes'])}")
        print(f"象限计数总结: {results['quadrant_counts']}")

        # 清理模拟权重文件 (可选)
        # shutil.rmtree(LOCAL_WEIGHTS_DIR, ignore_errors=True)

    except Exception as e:
        print(f"\n--- ❌ 运行示例时出错 ---")
        print(f"错误信息: {e}")
        logger.error(f"Main execution error: {e}")

"""