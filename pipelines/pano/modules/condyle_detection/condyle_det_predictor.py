# -*- coding: utf-8 -*-
import os
import sys
import logging
import numpy as np
import torch
import json
from ultralytics import YOLO

# 1. 引用根目录 (确保能找到 tools 和 pipelines)
sys.path.append(os.getcwd())

# 2. 引用 MinIO 配置和 Client 生成器
# 确保 tools/load_weight.py 存在且包含这些变量
from tools.load_weight import get_s3_client, S3_BUCKET_NAME, LOCAL_WEIGHTS_DIR

# 3. 引用格式化工具
try:
    # 尝试导入真实工具类
    from pipelines.pano.utils import pano_report_utils
except ImportError:
    # 如果导入失败，使用 Mock 类作为兜底，确保流程测试通畅
    class MockReportUtils:
        MORPHOLOGY_MAP = {
            0: {"detail": "髁突形态正常", "label": "正常"},
            1: {"detail": "髁突形态吸收", "label": "吸收"},
            2: {"detail": "髁突形态疑似异常", "label": "疑似"},
        }

        @staticmethod
        def format_joint_report(raw_features, analysis):
            left_feature = raw_features.get("left", {})
            right_feature = raw_features.get("right", {})
            left_morphology = left_feature.get("class_id", 0)
            right_morphology = right_feature.get("class_id", 0)
            left_conf = left_feature.get("confidence", 0.0)
            right_conf = right_feature.get("confidence", 0.0)
            left_detail = MockReportUtils.MORPHOLOGY_MAP.get(left_morphology, MockReportUtils.MORPHOLOGY_MAP[0])[
                "detail"]
            right_detail = MockReportUtils.MORPHOLOGY_MAP.get(right_morphology, MockReportUtils.MORPHOLOGY_MAP[0])[
                "detail"]
            return {
                "CondyleAssessment": {
                    "condyle_Left": {"Morphology": left_morphology, "IsSymmetrical": False, "Detail": left_detail,
                                     "Confidence": left_conf},
                    "condyle_Right": {"Morphology": right_morphology, "IsSymmetrical": False, "Detail": right_detail,
                                      "Confidence": right_conf},
                    "OverallSymmetry": 0, "Confidence_Overall": max(left_conf, right_conf)
                },
                "RamusSymmetry": False, "GonialAngleSymmetry": True, "Detail": "髁突分析完成。",
                "Confidence": max(left_conf, right_conf)
            }


    pano_report_utils = MockReportUtils()
    print("⚠️ WARNING: Could not import real pano_report_utils. Using MockReportUtils for robustness.")

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class JointPredictor:
    """
    髁突(关节)检测推理器 - YOLOv11
    """

    def __init__(self):
        # --- 配置区域 ---
        # MinIO 中的路径 (不含 Bucket 名)
        self.s3_weight_path = "weights/panoramic/candlye_detec_best.pt"

        # 拼接本地缓存的绝对路径
        self.local_weight_path = os.path.join(LOCAL_WEIGHTS_DIR, self.s3_weight_path)

        self.model = None
        self._init_model()

    def _init_model(self):
        """
        初始化流程：
        1. 检查本地是否有权重文件
        2. 如果没有，从 MinIO 下载
        3. 使用 ultralytics.YOLO 加载本地文件路径
        """
        logger.info(">>> [1/3] Initializing Model...")

        try:
            # 步骤 A: 确保权重文件存在
            self._ensure_weight_exists()

            # 步骤 B: 加载 YOLO
            logger.info(f"Loading YOLO weights from: {self.local_weight_path}")
            self.model = YOLO(self.local_weight_path)
            logger.info("✅ YOLO Model initialized successfully.")

        except Exception as e:
            logger.critical(f"❌ Failed to initialize YOLO model: {e}")
            self.model = None

    def _ensure_weight_exists(self):
        """
        检查本地缓存，不存在则下载
        """
        local_folder = os.path.dirname(self.local_weight_path)
        if not os.path.exists(local_folder):
            os.makedirs(local_folder)

        if not os.path.exists(self.local_weight_path):
            logger.info(f"Cache miss. Downloading from S3: {self.s3_weight_path} ...")
            try:
                s3 = get_s3_client()
                # 下载文件
                s3.download_file(S3_BUCKET_NAME, self.s3_weight_path, self.local_weight_path)
                logger.info("Download completed.")
            except Exception as e:
                logger.error(f"Download failed. Please check S3 config. Error: {e}")
                raise e
        else:
            logger.info(f"Cache hit. Found local weights.")

    def predict(self, image) -> dict:
        """
        执行推理
        Args:
            image: 图片路径(str) 或 Numpy Array (H,W,C)
        """
        if self.model is None:
            logger.error("Model not initialized.")
            return {}

        logger.info(">>> [2/3] Running Inference...")
        try:
            # 1. YOLO 推理
            # verbose=False 不打印默认的推理日志，保持清爽
            results = self.model(image, verbose=False)
            result = results[0]  # 取第一张图结果

            # 2. 解析 YOLO 结果 (Box, Class, Confidence)
            all_raw_features = []

            best_left_feature = {}
            best_right_feature = {}
            max_conf_left = -1.0
            max_conf_right = -1.0

            if result.boxes:
                for box in result.boxes:
                    # 转为标准 Python 数据类型
                    bbox = box.xyxy.cpu().numpy()[0].tolist()  # [x1, y1, x2, y2]
                    conf = float(box.conf.cpu().numpy()[0])
                    cls_id = int(box.cls.cpu().numpy()[0])
                    cls_name = result.names.get(cls_id, f"Class_{cls_id}")

                    feature_data = {
                        "bbox": bbox,
                        "class_name": cls_name,
                        "confidence": conf,
                        "class_id": cls_id  # 关键：传递 Class ID (0, 1, 2)
                    }

                    all_raw_features.append(feature_data)

                    # --- 选择最佳检测结果 (按置信度) ---
                    cls_name_lower = cls_name.lower()

                    if 'left' in cls_name_lower:
                        if conf > max_conf_left:
                            max_conf_left = conf
                            best_left_feature = feature_data
                    elif 'right' in cls_name_lower:
                        if conf > max_conf_right:
                            max_conf_right = conf
                            best_right_feature = feature_data
                    # ------------------------------------

            logger.info(f"Inference done. Detected {len(all_raw_features)} objects.")

            # 3. 准备分析元数据 (此处只模拟)
            analysis = {
                "model_type": "yolov11",
                "detected_count": len(all_raw_features),
                "image_shape": result.orig_shape,  # (Height, Width)
                "is_symmetric": True,  # 默认为True，除非有其他模块计算
                "metrics": {},
                "conclusion": "髁突形态学分类已完成。"
            }

            # 4. 格式化输出 (调用 Utils)
            logger.info(">>> [3/3] Formatting Report...")

            grouped_features = {
                "left": best_left_feature,
                "right": best_right_feature
            }

            standard_data = pano_report_utils.format_joint_report(
                raw_features=grouped_features,
                analysis=analysis
            )

            return {
                "standard_data": standard_data,
                "debug_raw": all_raw_features
            }

        except Exception as e:
            logger.error(f"❌ Prediction error: {e}")
            import traceback
            traceback.print_exc()
            return {}


# --- 自动化验证脚本 (无需真实图片) ---
if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("   开始 JointPredictor 全流程验证")
    print("=" * 50 + "\n")

    # 1. 生成虚拟图片 (模拟一张 640x640 的 3通道彩色图)
    print("📸 生成虚拟测试图片 (Random Noise)...")
    dummy_image = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)

    # 2. 初始化预测器
    predictor = JointPredictor()

    # 3. 执行预测
    if predictor.model:
        result = predictor.predict(dummy_image)

        print("\n" + "-" * 20 + " 验证结果 " + "-" * 20)
        if result:
            # 打印部分结果验证格式
            print("✅ 推理成功！")
            print("JSON 输出预览 (Standard Data):")
            print(json.dumps(result.get('standard_data'), indent=2, ensure_ascii=False))

            detected_num = len(result.get('debug_raw', []))
            if detected_num == 0:
                print("\n⚠️  注: 这是一个随机噪声虚拟图，未检测到目标是正常的 (Detected 0)。")
                print("    这证明了: 下载->加载->推理->输出 流程是通畅的。")
            else:
                print(f"\n⚠️  哇！在噪声图中检测到了 {detected_num} 个幻觉目标 (False Positives)，流程通畅。")
        else:
            print("❌ 推理返回为空，请检查日志错误。")
    else:
        print("❌ 模型初始化失败，无法进行推理。")

    print("\n" + "=" * 50)