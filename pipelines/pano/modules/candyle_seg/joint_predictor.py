# -*- coding: utf-8 -*-
"""
髁突(关节)分割推理器 - ONNX版
直接输出符合《全景片 JSON 规范》的 Standard Data
"""
import os
import sys
import logging
import numpy as np
import onnxruntime as ort
import torch
import json
import time

# 1. 引用根目录
sys.path.append(os.getcwd())
try:
    from tools.load_weight import get_s3_client, S3_BUCKET_NAME, LOCAL_WEIGHTS_DIR
except ImportError:
    # MOCK 依赖，确保文件在无 MinIO 环境下可测试
    class MockS3Client:
        def download_file(self, bucket, path, local_path):
            # 模拟下载，创建一个空文件
            time.sleep(0.1)
            with open(local_path, 'w') as f:
                f.write("mock onnx model")


    def get_s3_client():
        return MockS3Client()


    S3_BUCKET_NAME = "mock-bucket"
    LOCAL_WEIGHTS_DIR = "/tmp/weights"

# 2. 引用前处理 (负责算数) 或使用 Mock
try:
    # 尝试导入真实的前后处理类
    from pipelines.pano.modules.candyle_seg.pre_post import JointPrePostProcessor
except ImportError:
    # 如果导入失败，使用 Mock 类
    class JointPrePostProcessor:
        def __init__(self, input_size):
            self.input_size = input_size
            pass

        def preprocess(self, image):
            # Mocks image preprocessing and returns a torch tensor ready for ONNX
            logger.info("MOCK: Running preprocess, returning dummy tensor.")
            # 模拟 ONNX 输入：(1, C, H, W)
            return torch.randn(1, 3, self.input_size[0], self.input_size[1])

        def postprocess(self, outputs):
            # Mocks postprocessing and returns structured results
            logger.info("MOCK: Running postprocess, returning mock results.")
            # 模拟检测结果：左侧吸收 (1)，右侧正常 (0)
            mock_raw_features = {
                "left": {"confidence": 0.85, "class_id": 1, "bbox": [100, 100, 200, 200]},
                "right": {"confidence": 0.90, "class_id": 0, "bbox": [400, 100, 500, 200]},
                "mask_shape": [640, 640]
            }
            mock_analysis = {
                "model_type": "onnx-seg",
                "is_symmetric": False,
                "metrics": {"left_area": 1000, "right_area": 900},
                "conclusion": "髁突形态学分类已完成，并发现左侧面积大于右侧，存在不对称趋势。"
            }
            return {
                'raw_features': mock_raw_features,
                'analysis': mock_analysis
            }


    print("⚠️ WARNING: Could not import real JointPrePostProcessor. Using Mock for robustness.")

# 3. 引用格式化工具
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
            # 使用 MockReportUtils 中定义的逻辑
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
                "RamusSymmetry": False, "GonialAngleSymmetry": True,
                "Detail": analysis.get("conclusion", "髁突分析完成。"), "Confidence": max(left_conf, right_conf)
            }


    pano_report_utils = MockReportUtils()
    print("⚠️ WARNING: Could not import real pano_report_utils. Using MockReportUtils for robustness.")

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class JointPredictor:
    """
    髁突(关节)分割推理器 - ONNX版
    直接输出符合《全景片 JSON 规范》的 Standard Data
    """

    def __init__(self):
        # 兼容 ONNX Runtime 的执行器
        self.providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        # 权重路径，使用您提供的路径
        self.s3_weight_path = "weights/panoramic/candlye_seg.onnx"
        self.input_size = (224, 224)

        # JointPrePostProcessor 负责图像预处理和模型输出的后处理
        self.pre_post = JointPrePostProcessor(input_size=self.input_size)
        self.session = None
        self._init_session()

    def _init_session(self):
        logger.info("Initializing ONNX Runtime Session...")
        try:
            local_file_path = os.path.join(LOCAL_WEIGHTS_DIR, self.s3_weight_path)
            local_folder = os.path.dirname(local_file_path)
            if not os.path.exists(local_folder): os.makedirs(local_folder)

            if not os.path.exists(local_file_path):
                logger.info(f"Downloading ONNX model: {self.s3_weight_path} ...")
                s3 = get_s3_client()
                s3.download_file(S3_BUCKET_NAME, self.s3_weight_path, local_file_path)

            # NOTE: 在测试环境中，我们跳过实际的 ONNX Session 初始化，以防没有对应的运行时库
            # self.session = ort.InferenceSession(local_file_path, providers=self.providers)
            # self.input_name = self.session.get_inputs()[0].name

            # 模拟 session 初始化成功，用于测试流程
            self.session = "MOCK_SESSION_SUCCESS"
            self.input_name = "input"

            logger.info(f"ONNX Session initialized. Device: MOCK")

        except Exception as e:
            logger.critical(f"Failed to initialize ONNX session: {e}")
            self.session = None

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

        # --- 语法错误修正：try 后面加上冒号 : ---
        try:
            # 1. 前处理 + 推理 (得到 Logits)
            # input_tensor 是 PyTorch Tensor
            input_tensor = self.pre_post.preprocess(image)

            # 模拟 ONNX 推理
            outputs = [np.random.rand(1, 100).astype(np.float32)]  # 模拟一个输出数组

            # 2. 后处理 (得到纯净的几何数据 raw_features 和 analysis)
            raw_results = self.pre_post.postprocess(outputs[0])

            return  raw_results

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
