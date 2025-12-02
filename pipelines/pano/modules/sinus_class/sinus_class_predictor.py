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


class SinusClassPredictor:
    """
    上颌窦炎症分类器 (只负责分类)
    """

    def __init__(self, weights_key: str, **kwargs):
        self.providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        self.onnx_key = weights_key  # 配置驱动

        self.mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        self.std = np.array([0.229, 0.224, 0.225], dtype=np.float32)

        self.session = None
        self._init_session()

    def _download_if_needed(self, s3_key):
        local_path = os.path.join(LOCAL_WEIGHTS_DIR, s3_key)
        local_dir = os.path.dirname(local_path)
        if not os.path.exists(local_dir): os.makedirs(local_dir)
        if not os.path.exists(local_path):
            try:
                s3 = get_s3_client()
                if s3: s3.download_file(S3_BUCKET_NAME, s3_key, local_path)
            except Exception as e:
                logger.error(f"Download failed: {e}")
                return None
        return local_path

    def _init_session(self):
        logger.info(f"Initializing Sinus Class with {self.onnx_key}...")
        model_path = self._download_if_needed(self.onnx_key)
        if model_path and os.path.exists(model_path):
            try:
                self.session = ort.InferenceSession(model_path, providers=self.providers)
                self.input_name = self.session.get_inputs()[0].name
                logger.info("✅ Sinus Class Model Loaded.")
            except Exception as e:
                logger.error(f"Sinus Class init failed: {e}")

    def _preprocess(self, crop_img):
        # 针对 224x224 的 ResNet 输入处理
        img = cv2.resize(crop_img, (224, 224))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0
        img = (img - self.mean) / self.std
        img = img.transpose(2, 0, 1)
        return np.expand_dims(img, axis=0)

    def predict(self, crop_image) -> dict:
        """
        Args:
            crop_image: 已经裁剪好的上颌窦区域图片 (numpy array)
        """
        if not self.session or crop_image.size == 0:
            return {'is_inflam': False, 'confidence': 0.0}

        try:
            input_tensor = self._preprocess(crop_image)
            output = self.session.run(None, {self.input_name: input_tensor})[0]

            # Softmax
            exps = np.exp(output - np.max(output))
            probs = exps / np.sum(exps)
            pred_idx = np.argmax(probs)

            # 假设 0=Inflammation, 1=Normal (根据您之前的训练逻辑)
            is_inflam = (pred_idx == 0)
            conf = float(probs[0][pred_idx])

            return {'is_inflam': is_inflam, 'confidence': conf}

        except Exception as e:
            logger.error(f"Class predict error: {e}")
            return {'is_inflam': False, 'confidence': 0.0}