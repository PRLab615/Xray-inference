# -*- coding: utf-8 -*-
import os
import sys
import logging
import cv2
import numpy as np
import onnxruntime as ort

sys.path.append(os.getcwd())
from tools.weight_fetcher import get_s3_client, S3_BUCKET_NAME, LOCAL_WEIGHTS_DIR
# ▼▼▼ 1. 导入刚才写的 PrePostProcessor ▼▼▼
from pipelines.pano.modules.sinus_seg.pre_post import SinusPrePostProcessor

logger = logging.getLogger(__name__)


class SinusSegPredictor:
    """
    上颌窦分割预测器
    职责：
    1. 管理模型权重 (下载/加载)
    2. 管理 ONNX Session
    3. 持有 PrePostProcessor 实例 (供 Pipeline 调用)
    """

    def __init__(self, weights_key: str, **kwargs):
        """
        Args:
            weights_key: 从 config 传入的权重路径
            **kwargs: 吸收其他配置参数
        """
        self.providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        self.onnx_key = weights_key

        # ▼▼▼ 2. 初始化 PrePostProcessor ▼▼▼
        # Pipeline 会通过 self.modules['sinus_seg'].pre_post 访问它
        self.pre_post = SinusPrePostProcessor(seg_size=(512, 512))

        # 注意：不再需要 self.mean 和 self.std，因为 pre_post 里已经有了

        self.session = None
        self._init_session()

    def _download_if_needed(self, s3_key):
        # ... (保持原样) ...
        local_path = os.path.join(LOCAL_WEIGHTS_DIR, s3_key)
        local_dir = os.path.dirname(local_path)
        if not os.path.exists(local_dir): os.makedirs(local_dir)
        if not os.path.exists(local_path):
            logger.info(f"Downloading Seg model: {s3_key} ...")
            try:
                s3 = get_s3_client()
                if s3: s3.download_file(S3_BUCKET_NAME, s3_key, local_path)
            except Exception as e:
                logger.error(f"Download failed: {e}")
                return None
        return local_path

    def _init_session(self):
        # ... (保持原样) ...
        logger.info(f"Initializing Sinus Seg with {self.onnx_key}...")
        model_path = self._download_if_needed(self.onnx_key)
        if model_path and os.path.exists(model_path):
            try:
                self.session = ort.InferenceSession(model_path, providers=self.providers)
                self.input_name = self.session.get_inputs()[0].name
                logger.info("✅ Sinus Seg Model Loaded.")
            except Exception as e:
                logger.error(f"Sinus Seg init failed: {e}")

    # 注意：_preprocess 方法已被删除，使用 self.pre_post 替代

    def predict(self, image) -> dict:
        """
        Returns:
            dict: {
                'mask': np.array (全图尺寸, 用于兼容旧逻辑),
                'debug_raw': np.array (原始输出, 用于 Pipeline 进行左右切分)
            }
        """
        if not self.session: return {}

        try:
            from tools.timer import timer

            h, w = image.shape[:2]

            # 1. 预处理 (调用 pre_post)
            with timer.record("sinus_seg.pre"):
                # 返回的是 Tensor，转为 numpy 给 ONNX 用
                input_tensor = self.pre_post.preprocess_segmentation(image)
                input_numpy = input_tensor.numpy()

            # 2. 推理
            with timer.record("sinus_seg.inference"):
                output = self.session.run(None, {self.input_name: input_numpy})[0]

            # 3. 后处理 (生成全图 mask 用于简单展示，保留 raw output 给 pipeline)
            with timer.record("sinus_seg.post"):
                # 使用 pre_post 的工具函数解析 mask
                mask_512 = self.pre_post._parse_output_to_mask(output)

                # 还原尺寸
                mask_full = cv2.resize(mask_512.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)

            return {
                'mask': mask_full,  # 用于可视化
                'debug_raw': output  # ▼▼▼ 关键：把原始数据传出去，让 Pipeline 做高级切分
            }

        except Exception as e:
            logger.error(f"Seg predict error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}