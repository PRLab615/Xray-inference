# -*- coding: utf-8 -*-
import os
import sys
import logging
import cv2
import numpy as np
import onnxruntime as ort

sys.path.append(os.getcwd())
from tools.load_weight import get_s3_client, S3_BUCKET_NAME, LOCAL_WEIGHTS_DIR

logger = logging.getLogger(__name__)


class SinusSegPredictor:
    """
    上颌窦分割预测器 (只负责分割)
    """

    def __init__(self, weights_key: str, **kwargs):
        """
        Args:
            weights_key: 从 config 传入的权重路径
            **kwargs: 吸收其他配置参数
        """
        self.providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        self.onnx_key = weights_key  # 使用配置传入的路径

        # 预处理参数
        self.mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        self.std = np.array([0.229, 0.224, 0.225], dtype=np.float32)

        self.session = None
        self._init_session()

    def _download_if_needed(self, s3_key):
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
        logger.info(f"Initializing Sinus Seg with {self.onnx_key}...")
        model_path = self._download_if_needed(self.onnx_key)
        if model_path and os.path.exists(model_path):
            try:
                self.session = ort.InferenceSession(model_path, providers=self.providers)
                self.input_name = self.session.get_inputs()[0].name
                logger.info("✅ Sinus Seg Model Loaded.")
            except Exception as e:
                logger.error(f"Sinus Seg init failed: {e}")

    def _preprocess(self, img, size=(512, 512)):
        img = cv2.resize(img, size)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0
        img = (img - self.mean) / self.std
        img = img.transpose(2, 0, 1)
        return np.expand_dims(img, axis=0)

    def predict(self, image) -> dict:
        """
        Returns:
            dict: { 'mask': np.array (原图尺寸), 'bbox_list': [...] }
        """
        if not self.session: return {}

        try:
            from tools.timer import timer
            
            h, w = image.shape[:2]

            # 1. 预处理（单独计时）
            with timer.record("sinus_seg.pre"):
                input_tensor = self._preprocess(image, (512, 512))

            # 2. 推理（只计时模型推理）
            with timer.record("sinus_seg.inference"):
                output = self.session.run(None, {self.input_name: input_tensor})[0]

            # 3. 后处理（单独计时，包括耗时的resize操作）
            with timer.record("sinus_seg.post"):
                # 假设输出 shape 是 (1, 2, 512, 512) 或 (1, 1, 512, 512)
                if output.shape[1] > 1:
                    mask_512 = np.argmax(output, axis=1)[0]
                else:
                    mask_512 = (output[0, 0] > 0.5).astype(np.uint8)

                # 还原到原图尺寸（这个操作很耗时，不应该算在推理时间里）
                mask_full = cv2.resize(mask_512.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)

            return {'mask': mask_full}

        except Exception as e:
            logger.error(f"Seg predict error: {e}")
            return {}