# predictor.py
import sys
import logging
import os
import torch
from ultralytics import YOLO
from PIL import Image
import numpy as np
from typing import Dict, Any, List

# --- 原始写法 (容易报错) ---
# sys.path.append(os.getcwd())

# --- ✅ 稳健写法 (推荐) ---
# 1. 获取当前脚本的绝对路径
current_file_path = os.path.abspath(__file__)
# 2. 获取当前脚本所在的目录 (mandible_seg)
current_dir = os.path.dirname(current_file_path)
# 3. 向上找 4 层，定位到项目根目录 (Xray-inference)
#    路径结构: pipelines/pano/modules/mandible_seg/predictor.py (4层深)
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))

# 4. 将根目录加入 Python 搜索路径
if project_root not in sys.path:
    sys.path.append(project_root)

# --- 现在可以放心导入了 ---
from tools.load_weight import get_s3_client, S3_BUCKET_NAME, LOCAL_WEIGHTS_DIR, load_model_weights
from pipelines.pano.modules.implant_detect.pre_post import process_detections

logger = logging.getLogger(__name__)

# YOLO 模型的 S3 路径
YOLO_S3_PATH = "weights/panoramic/implant.pt"


class ImplantDetectionModule:
    """
    全景片植入物检测模块（YOLOv11实现），适配 load_model_weights 函数。
    """

    def __init__(self, device: str = None):
        """
        初始化植入物检测模块，加载权重。
        """
        if device is None:
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        else:
            self.device = device

        self.model: YOLO = self._load_model()

    def _load_model(self) -> YOLO:
        """
        加载 YOLOv11 模型。

        核心逻辑:
        1. 调用 load_model_weights 触发 MinIO 下载。
        2. 忽略其返回值 (state_dict)，因为 YOLO 需要文件路径。
        3. 构造本地路径，用 YOLO(path) 加载模型。
        """

        # 1. 触发 MinIO 下载 (利用其副作用: 文件将被下载到 local_weight_path)
        # 这里的返回值是 state_dict，我们不需要它，但它的执行保证了文件存在。
        weights_state_dict = load_model_weights(YOLO_S3_PATH, device='cpu', force_download=False)

        # 2. 构造本地文件路径 (load_model_weights 的副作用)
        local_weight_path = os.path.join(LOCAL_WEIGHTS_DIR, YOLO_S3_PATH)

        # 检查文件是否存在，如果下载失败 (weights_state_dict is None)，则抛出错误
        if weights_state_dict is None or not os.path.exists(local_weight_path):
            logger.error(f"YOLOv11 implant weights not found or download failed: {local_weight_path}")
            # 这里的异常是必要的，因为没有模型无法继续
            raise FileNotFoundError(f"YOLOv11 implant weights file not found after download attempt.")

        try:
            # 3. 使用 Ultralytics YOLO 框架加载模型 (需要本地文件路径)
            logger.info(f"Initializing Implant YOLO model from path: {local_weight_path} on {self.device}")
            model = YOLO(local_weight_path)
            model.to(self.device)
            model.eval()
            logger.info("YOLOv11 Implant Detection Model initialized successfully.")
            return model

        except Exception as e:
            logger.error(
                f"Failed to load or initialize YOLOv11 Implant model from path: {local_weight_path}. Error: {e}")
            raise

    @torch.no_grad()
    def predict(self, image: Image.Image) -> Dict[str, Any]:

        if not self.model:
            logger.error("Model is not loaded. Skipping prediction.")
            return {"implant_boxes": [], "quadrant_counts": {1: 0, 2: 0, 3: 0, 4: 0}}

        original_shape = image.size[::-1]
        logger.info("Starting YOLOv11 implant detection inference.")

        try:
            # 1. 执行 YOLO 推理
            results = self.model.predict(
                imgsz=640,
                source=image,
                conf=0.25,
                iou=0.45,
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