# -*- coding: utf-8 -*-
"""下颌骨分割推理器 - ONNX版"""

import os
import sys
import logging
import numpy as np
import onnxruntime as ort
import torch
from typing import Optional, List, Tuple

# --- 稳健路径设置 ---
current_file_path = os.path.abspath(__file__)
current_dir = os.path.dirname(current_file_path)
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

# 导入统一的权重获取工具
from tools.weight_fetcher import ensure_weight_file, WeightFetchError

# 引用下颌骨前处理
from pipelines.pano.modules.mandible_seg.pre_post import MandiblePrePostProcessor

# 引用格式化工具
from pipelines.pano.utils import pano_report_utils

logger = logging.getLogger(__name__)


class MandiblePredictor:
    """
    下颌骨(Mandible)分割推理器 - ONNX版

    职责:
    1. 从 S3 下载并加载 transunet_mandible.onnx
    2. 计算升支(Ramus)和下颌角(Gonial Angle)对称性
    3. 输出符合接口定义的 'JointAndMandible' 下半部分数据
    
    权重路径通过 config.yaml 统一配置，不再使用硬编码路径。
    """

    def __init__(
        self,
        *,
        weights_key: Optional[str] = None,
        weights_force_download: bool = False,
        input_size: Optional[List[int]] = None,
    ):
        """
        初始化下颌骨分割模块
        
        Args:
            weights_key: S3 权重路径（从 config.yaml 传入）
            weights_force_download: 是否强制重新下载权重
            input_size: 输入尺寸 [H, W]，默认 [224, 224]
        """
        self.weights_key = weights_key
        self.weights_force_download = weights_force_download
        
        # 优先 GPU
        self.providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']

        # 输入尺寸（必须与 TransUNet 导出 ONNX 时的尺寸一致）
        if input_size:
            self.input_size = tuple(input_size)
        else:
            self.input_size = (224, 224)

        # 实例化前处理工具
        self.pre_post = MandiblePrePostProcessor(input_size=self.input_size)
        self.session = None
        self.weights_path = None

        # 初始化模型
        self._init_session()

    def _resolve_weights_path(self) -> str:
        """
        解析权重文件路径
        
        优先级：
            1. 配置的 weights_key（从 config.yaml 传入，可通过 S3 下载）
            2. 环境变量 PANO_MANDIBLE_SEG_WEIGHTS（可选覆盖）
        """
        env_weights = os.getenv("PANO_MANDIBLE_SEG_WEIGHTS")
        
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
                    logger.info(f"Downloaded Mandible weights from S3 key '{candidate}' to {downloaded}")
                    return downloaded
                except WeightFetchError as e:
                    logger.warning(f"Failed to download from {origin}: {e}")
                    continue
        
        # 所有候选路径都失败
        error_msg = (
            f"Mandible segmentation model weights not found. "
            f"Please configure weights_key in config.yaml under pipelines.panoramic.modules.mandible_seg"
        )
        raise FileNotFoundError(error_msg)

    def _init_session(self):
        """解析权重路径并初始化 ONNX Session"""
        logger.info("Initializing Mandible ONNX Session...")

        try:
            # 解析权重路径
            self.weights_path = self._resolve_weights_path()

            # 创建推理会话
            self.session = ort.InferenceSession(self.weights_path, providers=self.providers)
            self.input_name = self.session.get_inputs()[0].name
            logger.info(f"Mandible Session initialized. Device: {ort.get_device()}")

        except Exception as e:
            logger.critical(f"Failed to initialize Mandible session: {e}")
            self.session = None
            raise

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

            return raw_results

            # # 4. 【关键步骤】调用 Utils 进行标准化格式化
            # # 将 raw_results['analysis'] 转换为符合接口定义的 JSON 片段
            # standard_data = pano_report_utils.format_mandible_report(
            #     analysis_result=raw_results.get("analysis", {})
            # )
            #


        except Exception as e:
            logger.error(f"Mandible Prediction error: {e}")
            import traceback
            traceback.print_exc()
            return {}