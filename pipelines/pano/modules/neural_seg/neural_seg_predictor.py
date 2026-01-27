# -*- coding: utf-8 -*-
"""
神经管(下颌神经管)分割推理器 - ONNX版
直接输出符合《全景片 JSON 规范》的 Standard Data

权重路径通过 config.yaml 统一配置，不再使用硬编码路径。
"""
import os
import sys
import logging
import numpy as np
import onnxruntime as ort
import json
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

# 引用前处理 (负责算数) - 假设您会创建一个 neural_seg 模块
try:
    from pipelines.pano.modules.neural_seg.pre_post import NeuralPrePostProcessor
    logger.info("Successfully imported NeuralPrePostProcessor from neural_seg.pre_post")
except ImportError as e:
    logger.error(f"Failed to import NeuralPrePostProcessor: {e}")
    try:
        from importlib.machinery import SourceFileLoader
        pre_post_path = os.path.join(os.path.dirname(__file__), 'pre_post.py')
        NeuralPrePostProcessor = SourceFileLoader('nerual_pre_post', pre_post_path).load_module().NeuralPrePostProcessor
        logger.info("Loaded NeuralPrePostProcessor via SourceFileLoader from neural_seg/pre_post.py")
    except Exception as e2:
        logger.error(f"Fallback load of NeuralPrePostProcessor failed: {e2}")
        class MockNeuralPrePostProcessor:
            def __init__(self, input_size): self.input_size = input_size
            def preprocess(self, img):
                return np.zeros((1, 3, *self.input_size), dtype=np.float32)
            def postprocess(self, out):
                return {"mask_shape": (self.input_size[0], self.input_size[1]), "raw_features": {"left": {"exists": False}, "right": {"exists": False}}, "analysis": {"is_symmetric": False}}
        NeuralPrePostProcessor = MockNeuralPrePostProcessor
        logger.warning("Using MockNeuralPrePostProcessor as fallback.")

# 引用格式化工具
try:
    from pipelines.pano.utils import pano_report_utils
except ImportError:
    class MockReportUtils:
        @staticmethod
        def format_neural_report(masks_info):
            return {
                "NeuralCanalAssessment": {
                    "Left": {"Detected": bool(masks_info.get("left")), "Area": 0},
                    "Right": {"Detected": bool(masks_info.get("right")), "Area": 0}
                },
                "Conclusion": "神经管分割完成。"
            }


    pano_report_utils = MockReportUtils()
    logger.warning("Could not import real pano_report_utils. Using MockReportUtils.")


class NeuralPredictor:
    """
    神经管(下颌神经管)分割推理器 - ONNX版

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
        初始化神经管分割模块

        Args:
            weights_key: S3 权重路径（从 config.yaml 传入）
            weights_force_download: 是否强制重新下载权重
            input_size: 输入尺寸 [H, W]，默认 [224, 224] (TransUNet 标准输入)
        """
        self.weights_key = weights_key
        self.weights_force_download = weights_force_download

        # 兼容 ONNX Runtime 的执行器
        # 优先使用 CUDA，如果没有则回退到 CPU
        self.providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']

        # 输入尺寸
        if input_size:
            self.input_size = tuple(input_size)
        else:
            self.input_size = (224, 224)

        # NeuralPrePostProcessor 负责图像预处理和模型输出的后处理
        # (例如：Mask二值化、左右分割、resize回原图)
        self.pre_post = NeuralPrePostProcessor(input_size=self.input_size)

        self.session = None
        self.weights_path = None
        self._init_session()

    def _resolve_weights_path(self) -> str:
        """
        解析权重文件路径

        优先级：
            1. 配置的 weights_key
            2. 环境变量 PANO_NEURAL_SEG_WEIGHTS
        """
        env_weights = os.getenv("PANO_NEURAL_SEG_WEIGHTS")

        candidates = [
            ("weights_key", self.weights_key),
            ("env", env_weights),
        ]

        for origin, candidate in candidates:
            if not candidate:
                continue

            if os.path.exists(candidate):
                logger.info(f"Using local weights file: {candidate} (from {origin})")
                return candidate

            if origin == "weights_key":
                try:
                    downloaded = ensure_weight_file(candidate, force_download=self.weights_force_download)
                    logger.info(f"Downloaded Neural Seg weights from S3 key '{candidate}' to {downloaded}")
                    return downloaded
                except WeightFetchError as e:
                    logger.warning(f"Failed to download from {origin}: {e}")
                    continue

        error_msg = (
            f"Neural canal segmentation model weights not found. "
            f"Please configure weights_key in config.yaml under pipelines.panoramic.modules.neural_seg"
        )
        raise FileNotFoundError(error_msg)

    def _init_session(self):
        """解析权重路径并初始化 ONNX Session"""
        logger.info("Initializing Neural Seg ONNX Runtime Session...")
        try:
            self.weights_path = self._resolve_weights_path()

            # 初始化 ONNX Session
            self.session = ort.InferenceSession(self.weights_path, providers=self.providers)
            self.input_name = self.session.get_inputs()[0].name

            actual_providers = self.session.get_providers()
            logger.info(f"ONNX Session initialized. Providers: {actual_providers}")
            logger.info(f"Input name: {self.input_name}")

            # 简单的 Warmup (可选)
            # try:
            #     dummy = np.zeros((1, 3, *self.input_size), dtype=np.float32)
            #     self.session.run(None, {self.input_name: dummy})
            # except Exception:
            #     pass

        except Exception as e:
            logger.critical(f"Failed to initialize ONNX session: {e}")
            self.session = None
            raise

    def predict(self, image) -> dict:
        """
        执行推理
        Returns:
            dict: { "left": mask_left, "right": mask_right, "full_mask": ... }
        """
        if self.session is None:
            logger.error("Model not initialized.")
            return {}

        logger.info(">>> [2/3] Running Neural Seg Inference...")

        try:
            # 1. 前处理 (Pre-processing)
            # 这里调用 NeuralPrePostProcessor，它应该负责：
            # Resize(224) -> Normalize -> CHW -> Tensor/Numpy
            with timer.record("neural_seg.pre"):
                input_tensor = self.pre_post.preprocess(image)
                # 确保转为 numpy (如果是 tensor)
                if hasattr(input_tensor, 'cpu'):
                    input_numpy = input_tensor.cpu().numpy()
                else:
                    input_numpy = input_tensor

                logger.info(f"[predict] input shape: {input_numpy.shape}")

            # 2. ONNX 推理 (Inference)
            with timer.record("neural_seg.inference"):
                # 执行推理
                onnx_outputs = self.session.run(None, {self.input_name: input_numpy})
                # TransUNet 输出通常是 (1, num_classes, H, W)
                logger.info(f"[predict] ONNX output shape: {onnx_outputs[0].shape}")

            # 3. 后处理 (Post-processing)
            # 这里调用 NeuralPrePostProcessor，它应该负责：
            # Argmax/Threshold -> Resize回原图 -> 切分左右侧 -> 过滤噪点
            with timer.record("neural_seg.post"):
                raw_results = self.pre_post.postprocess(onnx_outputs[0])

            return raw_results

        except Exception as e:
            logger.error(f"ONNX Prediction error: {e}")
            import traceback
            traceback.print_exc()
            return {}


# --- 自动化验证脚本 ---
if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("   开始 NeuralPredictor (ONNX Segmentation) 全流程验证")
    print("=" * 50 + "\n")

    # 1. 生成虚拟图片
    print("📸 生成虚拟测试图片...")
    dummy_image = np.random.randint(0, 255, (1000, 2000, 3), dtype=np.uint8)

    # 2. 初始化预测器 (模拟本地文件存在的情况)
    # 注意：运行前请确保 config.yaml 配置正确或 weights_key 指向真实文件
    try:
        predictor = NeuralPredictor(
            weights_key="weights/panoramic/best_model_ramus_224.onnx"
        )

        # 3. 执行预测
        if predictor.session:
            result = predictor.predict(dummy_image)

            print("\n" + "-" * 20 + " 验证结果 " + "-" * 20)
            if result:
                print("✅ 推理成功！")
                print(
                    f"Full Mask Shape: {result.get('full_mask', 'N/A').shape if result.get('full_mask') is not None else 'None'}")
                print(f"Left Detected: {result.get('left') is not None}")
                print(f"Right Detected: {result.get('right') is not None}")
            else:
                print("❌ 推理返回为空。")
    except Exception as e:
        print(f"❌ 初始化失败 (可能是缺少模型文件): {e}")

    print("\n" + "=" * 50)