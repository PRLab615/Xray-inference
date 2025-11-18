# -*- coding: utf-8 -*-
import os
import sys
import logging
import numpy as np
import onnxruntime as ort
import torch

# 1. 引用根目录
sys.path.append(os.getcwd())
from tools.load_weight import get_s3_client, S3_BUCKET_NAME, LOCAL_WEIGHTS_DIR

# 2. 引用前处理 (负责算数)
from pipelines.pano.modules.candyle_seg.pre_post import JointPrePostProcessor

# 3. 【新增】引用格式化工具 (负责规范)
# 确保 pipelines/pano/utils/pano_report_utils.py 里面有 format_joint_report 函数
from pipelines.pano.utils import pano_report_utils

logger = logging.getLogger(__name__)


class JointPredictor:
    """
    髁突(关节)分割推理器 - ONNX版
    直接输出符合《全景片 JSON 规范》的 Standard Data
    """

    def __init__(self):
        self.providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        self.s3_weight_path = "weights/panoramic/candlye_seg.onnx"
        self.input_size = (224, 224)

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

            self.session = ort.InferenceSession(local_file_path, providers=self.providers)
            self.input_name = self.session.get_inputs()[0].name
            logger.info(f"ONNX Session initialized. Device: {ort.get_device()}")

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
            return {}

        try:
            # 1. 前处理 + 推理 (得到 Logits)
            input_tensor = self.pre_post.preprocess(image)
            input_numpy = input_tensor.cpu().numpy()
            outputs = self.session.run(None, {self.input_name: input_numpy})

            # 2. 后处理 (得到纯净的几何数据 raw_features 和 analysis)
            # 这里的 postprocess 应该返回 { 'raw_features': ..., 'analysis': ... }
            raw_results = self.pre_post.postprocess(outputs[0])

            # 3. 【集成测试关键点】调用 Utils 进行格式化
            # 将 pre_post 的数学结果 -> 转化为 JSON 业务数据
            standard_joint_data = pano_report_utils.format_joint_report(
                raw_features=raw_results.get('raw_features', {}),
                analysis=raw_results.get('analysis', {})
            )

            # 4. 返回结果
            # 我们把标准数据放在 'standard_data' 字段里，方便测试查看
            return {
                "standard_data": standard_joint_data,
                "debug_raw": raw_results  # 保留原始数据用于 Debug
            }

        except Exception as e:
            logger.error(f"ONNX Prediction error: {e}")
            import traceback
            traceback.print_exc()
            return {}