# -*- coding: utf-8 -*-
import os
import sys
import logging
import numpy as np
import onnxruntime as ort
import torch

# --- 1. 引用根目录工具 (S3 配置) ---
sys.path.append(os.getcwd())
from tools.load_weight import get_s3_client, S3_BUCKET_NAME, LOCAL_WEIGHTS_DIR

# --- 2. 引用下颌骨前处理 (逻辑与算数) ---
# 假设前处理文件在 pipelines/pano/modules/mandible/pre_post.py
from pipelines.pano.modules.mandible_seg.pre_post import MandiblePrePostProcessor

# --- 3. 引用格式化工具 (JSON 规范) ---
from pipelines.pano.utils import pano_report_utils

logger = logging.getLogger(__name__)


class MandiblePredictor:
    """
    下颌骨(Mandible)分割推理器 - ONNX版

    职责:
    1. 下载并加载 transunet_mandible.onnx
    2. 计算升支(Ramus)和下颌角(Gonial Angle)对称性
    3. 输出符合接口定义的 'JointAndMandible' 下半部分数据
    """

    def __init__(self):
        # 优先 GPU
        self.providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']

        # --- 配置: 线上权重路径 ---
        # 桶内完整路径: teeth/weights/panoramic/transunet_mandible.onnx
        self.s3_weight_path = "weights/panoramic/transunet_mandible.onnx"

        # --- 配置: 输入尺寸 ---
        # 必须与 TransUNet 导出 ONNX 时的尺寸一致
        self.input_size = (224, 224)

        # 实例化前处理工具
        self.pre_post = MandiblePrePostProcessor(input_size=self.input_size)
        self.session = None

        # 初始化模型
        self._init_session()

    def _init_session(self):
        """下载 ONNX 文件并初始化 Session"""
        logger.info("Initializing Mandible ONNX Session...")

        try:
            # 1. 准备本地缓存路径
            local_file_path = os.path.join(LOCAL_WEIGHTS_DIR, self.s3_weight_path)
            local_folder = os.path.dirname(local_file_path)
            if not os.path.exists(local_folder):
                os.makedirs(local_folder)

            # 2. 下载权重 (如果本地没有)
            if not os.path.exists(local_file_path):
                logger.info(f"Downloading Mandible model: {self.s3_weight_path} ...")
                s3 = get_s3_client()
                s3.download_file(S3_BUCKET_NAME, self.s3_weight_path, local_file_path)
                logger.info("Download completed.")
            else:
                logger.info(f"Using cached Mandible model: {local_file_path}")

            # 3. 创建推理会话
            self.session = ort.InferenceSession(local_file_path, providers=self.providers)
            self.input_name = self.session.get_inputs()[0].name
            logger.info(f"Mandible Session initialized. Device: {ort.get_device()}")

        except Exception as e:
            logger.critical(f"Failed to initialize Mandible session: {e}")
            self.session = None

    def predict(self, image) -> dict:
        """
        执行推理

        Returns:
            dict: {
                "mandible_standard_data": { RamusSymmetry, GonialAngleSymmetry, Detail, Confidence },
                "mask_shape": (H, W),
                "debug_metrics": dict
            }
        """
        if self.session is None:
            logger.warning("Mandible Session not initialized, returning empty.")
            return {}

        try:
            # 1. 前处理 (Image -> Tensor)
            input_tensor = self.pre_post.preprocess(image)

            # 转 Numpy 喂给 ONNX
            input_numpy = input_tensor.cpu().numpy()

            # 2. ONNX 推理
            outputs = self.session.run(None, {self.input_name: input_numpy})
            raw_logits = outputs[0]

            # 3. 后处理 (解析 Mask -> 几何计算 -> 获得 analysis 字典)
            # pre_post 返回: { "analysis": {...}, "mask_shape": ..., "raw_features": ... }
            raw_results = self.pre_post.postprocess(raw_logits)

            # 4. 【关键步骤】调用 Utils 进行标准化格式化
            # 将 raw_results['analysis'] 转换为符合接口定义的 JSON 片段
            standard_data = pano_report_utils.format_mandible_report(
                analysis_result=raw_results.get("analysis", {})
            )

            return {
                "mandible_standard_data": standard_data,
                "mask_shape": raw_results.get("mask_shape"),
                "debug_metrics": raw_results.get("analysis", {}).get("Metrics")
            }

        except Exception as e:
            logger.error(f"Mandible Prediction error: {e}")
            import traceback
            traceback.print_exc()
            return {}