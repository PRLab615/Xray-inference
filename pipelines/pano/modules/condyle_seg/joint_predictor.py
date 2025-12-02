# -*- coding: utf-8 -*-
"""
髁突(关节)分割推理器 - ONNX版
直接输出符合《全景片 JSON 规范》的 Standard Data

权重路径通过 config.yaml 统一配置，不再使用硬编码路径。
"""
import os
import sys
import logging
import numpy as np
import onnxruntime as ort
import torch
import json
import time
from typing import Optional, List

# 初始化 logger
logger = logging.getLogger(__name__)

# --- 稳健路径设置 ---
current_file_path = os.path.abspath(__file__)
current_dir = os.path.dirname(current_file_path)
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

# 导入统一的权重获取工具
from tools.weight_fetcher import ensure_weight_file, WeightFetchError
from tools.timer import timer

# 引用前处理 (负责算数)
try:
    from pipelines.pano.modules.condyle_seg.pre_post import JointPrePostProcessor
    logger.info("Successfully imported JointPrePostProcessor from condyle_seg.pre_post")
except ImportError as e:
    logger.error(f"Failed to import JointPrePostProcessor: {e}")
    raise ImportError("JointPrePostProcessor is required but could not be imported!") from e

# 引用格式化工具
try:
    from pipelines.pano.utils import pano_report_utils
except ImportError:
    # 如果导入失败，使用 Mock 类作为兜底
    class MockReportUtils:
        MORPHOLOGY_MAP = {0: {"detail": "髁突形态正常", "label": "正常"},
                          1: {"detail": "髁突形态吸收", "label": "吸收"},
                          2: {"detail": "髁突形态疑似异常", "label": "疑似"}}

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
                "RamusSymmetry": False, "GonialAngleSymmetry": True,
                "Detail": analysis.get("conclusion", "髁突分析完成。"), "Confidence": max(left_conf, right_conf)
            }


    pano_report_utils = MockReportUtils()
    logger.warning("Could not import real pano_report_utils. Using MockReportUtils.")


class JointPredictor:
    """
    髁突(关节)分割推理器 - ONNX版
    直接输出符合《全景片 JSON 规范》的 Standard Data
    
    权重路径通过 config.yaml 统一配置。
    """

    def __init__(
        self,
        *,
        weights_key: Optional[str] = None,
        weights_force_download: bool = False,
        input_size: Optional[List[int]] = None,
    ):
        """
        初始化髁突分割模块
        
        Args:
            weights_key: S3 权重路径（从 config.yaml 传入）
            weights_force_download: 是否强制重新下载权重
            input_size: 输入尺寸 [H, W]，默认 [224, 224]
        """
        self.weights_key = weights_key
        self.weights_force_download = weights_force_download
        
        # 兼容 ONNX Runtime 的执行器
        self.providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        
        # 输入尺寸
        if input_size:
            self.input_size = tuple(input_size)
        else:
            self.input_size = (224, 224)

        # JointPrePostProcessor 负责图像预处理和模型输出的后处理
        self.pre_post = JointPrePostProcessor(input_size=self.input_size)
        self.session = None
        self.weights_path = None
        self._init_session()

    def _resolve_weights_path(self) -> str:
        """
        解析权重文件路径
        
        优先级：
            1. 配置的 weights_key（从 config.yaml 传入，可通过 S3 下载）
            2. 环境变量 PANO_CONDYLE_SEG_WEIGHTS（可选覆盖）
        """
        env_weights = os.getenv("PANO_CONDYLE_SEG_WEIGHTS")
        
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
                    logger.info(f"Downloaded Condyle Seg weights from S3 key '{candidate}' to {downloaded}")
                    return downloaded
                except WeightFetchError as e:
                    logger.warning(f"Failed to download from {origin}: {e}")
                    continue
        
        # 所有候选路径都失败
        error_msg = (
            f"Condyle segmentation model weights not found. "
            f"Please configure weights_key in config.yaml under pipelines.panoramic.modules.condyle_seg"
        )
        raise FileNotFoundError(error_msg)

    def _init_session(self):
        """解析权重路径并初始化 ONNX Session"""
        logger.info("Initializing Condyle Seg ONNX Runtime Session...")
        try:
            # 解析权重路径
            self.weights_path = self._resolve_weights_path()

            # 初始化 ONNX Session
            self.session = ort.InferenceSession(self.weights_path, providers=self.providers)
            self.input_name = self.session.get_inputs()[0].name
            
            # 获取实际使用的 provider
            actual_providers = self.session.get_providers()
            logger.info(f"ONNX Session initialized. Providers: {actual_providers}")
            logger.info(f"Input name: {self.input_name}")

        except Exception as e:
            logger.critical(f"Failed to initialize ONNX session: {e}")
            self.session = None
            raise

    def predict(self, image) -> dict:
        """
        执行推理
        Returns:
            dict: { "standard_data": {...}, "mask_shape": ... }
        """
        if self.session is None:
            logger.error("Model not initialized.")
            return {}

        logger.info(">>> [2/3] Running Inference...")

        try:
            # 1. 前处理 (Pre-processing)
            with timer.record("condyle_seg.pre"):
                input_tensor = self.pre_post.preprocess(image)
                logger.info(f"[predict] input_tensor shape: {input_tensor.shape}")

            # 2. ONNX 推理 (Inference)
            with timer.record("condyle_seg.inference"):
                # 将 PyTorch tensor 转换为 numpy (ONNX Runtime 需要 numpy)
                input_numpy = input_tensor.cpu().numpy()
                logger.info(f"[predict] Running ONNX inference with input shape: {input_numpy.shape}")
                
                # 执行推理
                onnx_outputs = self.session.run(None, {self.input_name: input_numpy})
                logger.info(f"[predict] ONNX output count: {len(onnx_outputs)}, first output shape: {onnx_outputs[0].shape}")

            # 3. 后处理 (Post-processing)
            with timer.record("condyle_seg.post"):
                raw_results = self.pre_post.postprocess(onnx_outputs[0])

            return raw_results

            # # 3. 【集成测试关键点】调用 Utils 进行格式化
            # logger.info(">>> [3/3] Formatting Report...")
            #
            # standard_joint_data = pano_report_utils.format_joint_report(
            #     raw_features=raw_results.get('raw_features', {}),
            #     analysis=raw_results.get('analysis', {})
            # )
            #
            # # 4. 返回结果
            # return {
            #     "standard_data": standard_joint_data,
            #     "debug_raw": raw_results  # 保留原始数据用于 Debug
            # }

        except Exception as e:
            logger.error(f"ONNX Prediction error: {e}")
            import traceback
            traceback.print_exc()
            return {}


# # --- 自动化验证脚本 (无需真实图片) ---
# if __name__ == "__main__":
#     print("\n" + "=" * 50)
#     print("   开始 JointPredictor (ONNX Segmentation) 全流程验证")
#     print("=" * 50 + "\n")
#
#     # 1. 生成虚拟图片
#     print("📸 生成虚拟测试图片 (Random Noise)...")
#     dummy_image = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
#
#     # 2. 初始化预测器
#     predictor = JointPredictor()
#
#     # 3. 执行预测
#     if predictor.session:
#         result = predictor.predict(dummy_image)
#
#         print("\n" + "-" * 20 + " 验证结果 " + "-" * 20)
#         if result:
#             # 打印部分结果验证格式
#             print("✅ 推理成功！")
#             print("JSON 输出预览 (Standard Data):")
#             print(json.dumps(result.get('standard_data'), indent=2, ensure_ascii=False))
#
#             print("\n💡 关键字段解释：")
#             print(
#                 f"   - 左髁突形态 (Morphology): {result['standard_data']['CondyleAssessment']['condyle_Left']['Morphology']} (1=吸收)")
#             print(
#                 f"   - 右髁突形态 (Morphology): {result['standard_data']['CondyleAssessment']['condyle_Right']['Morphology']} (0=正常)")
#             print(
#                 f"   - 总体对称性 (OverallSymmetry): {result['standard_data']['CondyleAssessment']['OverallSymmetry']} (非0代表不对称)")
#         else:
#             print("❌ 推理返回为空，请检查日志错误。")
#     else:
#         print("❌ 模型初始化失败，无法进行推理。")
#
#     print("\n" + "=" * 50)
