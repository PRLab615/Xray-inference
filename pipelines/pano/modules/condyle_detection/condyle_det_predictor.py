# -*- coding: utf-8 -*-
"""
髁突(关节)检测推理器 - YOLOv11

权重路径通过 config.yaml 统一配置，不再使用硬编码路径。
"""
import os
import sys
import logging
import numpy as np
import torch
import json
from typing import Optional
from ultralytics import YOLO

# --- 稳健路径设置 ---
current_file_path = os.path.abspath(__file__)
current_dir = os.path.dirname(current_file_path)
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

# 导入统一的权重获取工具
from tools.weight_fetcher import ensure_weight_file, WeightFetchError

# 引用格式化工具
try:
    from pipelines.pano.utils import pano_report_utils
except ImportError:
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
            left_detail = MockReportUtils.MORPHOLOGY_MAP.get(left_morphology, MockReportUtils.MORPHOLOGY_MAP[0])["detail"]
            right_detail = MockReportUtils.MORPHOLOGY_MAP.get(right_morphology, MockReportUtils.MORPHOLOGY_MAP[0])["detail"]
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
    logging.warning("Could not import real pano_report_utils. Using MockReportUtils.")

logger = logging.getLogger(__name__)

# 类名到形态学分类的映射
CLASS_NAME_TO_MORPHOLOGY = {
    'condyle_normal': 0,      # 正常
    'condyle_resorption': 1,  # 吸收
    'condyle_suspect': 2,     # 疑似异常
    'normal': 0,              # 兼容简化版
    'resorption': 1,
    'suspect': 2
}


class JointPredictor:
    """
    髁突(关节)检测推理器 - YOLOv11
    
    权重路径通过 config.yaml 统一配置。
    """

    def __init__(
        self,
        *,
        weights_key: Optional[str] = None,
        weights_force_download: bool = False,
        device: Optional[str] = None,
    ):
        """
        初始化髁突检测模块
        
        Args:
            weights_key: S3 权重路径（从 config.yaml 传入）
            weights_force_download: 是否强制重新下载权重
            device: 推理设备（"0", "cpu" 等）
        """
        self.weights_key = weights_key
        self.weights_force_download = weights_force_download
        
        # 处理 device 参数
        # config.yaml 中 device: "0" 表示 GPU 0，"cpu" 表示 CPU
        if device is None:
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        elif device == "cpu":
            self.device = 'cpu'
        else:
            # "0", "1" 等数字字符串表示 GPU 索引
            self.device = f'cuda:{device}' if torch.cuda.is_available() else 'cpu'

        self.weights_path = None
        self.model = None
        self._init_model()

    def _resolve_weights_path(self) -> str:
        """
        解析权重文件路径
        
        优先级：
            1. 配置的 weights_key（从 config.yaml 传入，可通过 S3 下载）
            2. 环境变量 PANO_CONDYLE_DET_WEIGHTS（可选覆盖）
        """
        env_weights = os.getenv("PANO_CONDYLE_DET_WEIGHTS")
        
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
                    logger.info(f"Downloaded Condyle Det weights from S3 key '{candidate}' to {downloaded}")
                    return downloaded
                except WeightFetchError as e:
                    logger.warning(f"Failed to download from {origin}: {e}")
                    continue
        
        # 所有候选路径都失败
        error_msg = (
            f"Condyle detection model weights not found. "
            f"Please configure weights_key in config.yaml under pipelines.panoramic.modules.condyle_det"
        )
        raise FileNotFoundError(error_msg)

    def _init_model(self):
        """解析权重路径并初始化 YOLO 模型"""
        logger.info("Initializing Condyle Detection YOLO Model...")

        try:
            # 解析权重路径
            self.weights_path = self._resolve_weights_path()

            # 加载 YOLO
            logger.info(f"Loading YOLO weights from: {self.weights_path}")
            logger.info(f"CUDA available: {torch.cuda.is_available()}, Target device: {self.device}")
            self.model = YOLO(self.weights_path)
            # YOLO 模型不需要手动调用 .to()，在 predict 时指定 device 即可
            logger.info("YOLO Model initialized successfully.")

        except Exception as e:
            logger.critical(f"Failed to initialize YOLO model: {e}")
            self.model = None
            raise

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

            # 获取图像宽度，用于判断左右侧
            image_width = result.orig_shape[1]  # (Height, Width)
            image_center_x = image_width / 2

            if result.boxes:
                for box in result.boxes:
                    # 转为标准 Python 数据类型
                    bbox = box.xyxy.cpu().numpy()[0].tolist()  # [x1, y1, x2, y2]
                    conf = float(box.conf.cpu().numpy()[0])
                    cls_id = int(box.cls.cpu().numpy()[0])
                    cls_name = result.names.get(cls_id, f"Class_{cls_id}")

                    # 计算BBox中心点的x坐标
                    bbox_center_x = (bbox[0] + bbox[2]) / 2

                    # 从类名推导形态学分类 (morphology)
                    # 优先使用类名映射，如果找不到则使用原始class_id
                    morphology = CLASS_NAME_TO_MORPHOLOGY.get(cls_name.lower(), cls_id)

                    feature_data = {
                        "bbox": bbox,
                        "class_name": cls_name,
                        "confidence": conf,
                        "class_id": morphology  # 使用形态学分类 (0=正常, 1=吸收, 2=疑似)
                    }

                    all_raw_features.append(feature_data)

                    # --- 根据BBox位置判断左右侧 (左半部分=左侧，右半部分=右侧) ---
                    if bbox_center_x < image_center_x:
                        # 左侧髁突
                        if conf > max_conf_left:
                            max_conf_left = conf
                            best_left_feature = feature_data
                    else:
                        # 右侧髁突
                        if conf > max_conf_right:
                            max_conf_right = conf
                            best_right_feature = feature_data
                    # ------------------------------------

            logger.info(f"Inference done. Detected {len(all_raw_features)} objects.")
            logger.info(f"Image dimensions: {result.orig_shape}, center_x: {image_center_x}")
            logger.info(f"Left feature selected: {bool(best_left_feature)} (conf: {max_conf_left if best_left_feature else 'N/A'})")
            logger.info(f"Right feature selected: {bool(best_right_feature)} (conf: {max_conf_right if best_right_feature else 'N/A'})")

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
            return grouped_features

            # standard_data = pano_report_utils.format_joint_report(
            #     raw_features=grouped_features,
            #     analysis=analysis
            # )


            # return {
            #     "standard_data": standard_data,
            #     "debug_raw": all_raw_features
            # }


        except Exception as e:
            logger.error(f"❌ Prediction error: {e}")
            import traceback
            traceback.print_exc()
            return {}


# # --- 自动化验证脚本 (无需真实图片) ---
# if __name__ == "__main__":
#     print("\n" + "=" * 50)
#     print("   开始 JointPredictor 全流程验证")
#     print("=" * 50 + "\n")
#
#     # 1. 生成虚拟图片 (模拟一张 640x640 的 3通道彩色图)
#     print("📸 生成虚拟测试图片 (Random Noise)...")
#     dummy_image = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
#
#     # 2. 初始化预测器
#     predictor = JointPredictor()
#
#     # 3. 执行预测
#     if predictor.model:
#         result = predictor.predict(dummy_image)
#
#         print("\n" + "-" * 20 + " 验证结果 " + "-" * 20)
#         if result:
#             # 打印部分结果验证格式
#             print("✅ 推理成功！")
#             print("JSON 输出预览 (Standard Data):")
#             print(json.dumps(result.get('standard_data'), indent=2, ensure_ascii=False))
#
#             detected_num = len(result.get('debug_raw', []))
#             if detected_num == 0:
#                 print("\n⚠️  注: 这是一个随机噪声虚拟图，未检测到目标是正常的 (Detected 0)。")
#                 print("    这证明了: 下载->加载->推理->输出 流程是通畅的。")
#             else:
#                 print(f"\n⚠️  哇！在噪声图中检测到了 {detected_num} 个幻觉目标 (False Positives)，流程通畅。")
#         else:
#             print("❌ 推理返回为空，请检查日志错误。")
#     else:
#         print("❌ 模型初始化失败，无法进行推理。")
#
#     print("\n" + "=" * 50)