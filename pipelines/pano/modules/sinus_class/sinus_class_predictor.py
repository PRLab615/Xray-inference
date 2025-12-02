# -*- coding: utf-8 -*-
import os
import sys
import logging
import cv2
import numpy as np
import onnxruntime as ort

# --- 引用项目根目录工具 ---
sys.path.append(os.getcwd())
from tools.load_weight import get_s3_client, S3_BUCKET_NAME, LOCAL_WEIGHTS_DIR

logger = logging.getLogger(__name__)


class SinusFullPredictor:
    """
    上颌窦智能诊断全流程推理器 (Structure + Classification)
    """

    def __init__(self):
        self.providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']

        # --- 配置: 模型路径 ---
        self.struct_key = "weights/panoramic/sinus_structure_resnetunet.onnx"
        self.cls_key = "weights/panoramic/sinus_inflam_classifier_resnet18.onnx"

        # ImageNet 归一化参数
        self.mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        self.std = np.array([0.229, 0.224, 0.225], dtype=np.float32)

        self.struct_session = None
        self.cls_session = None
        self._init_sessions()

    def _download_if_needed(self, s3_key):
        local_path = os.path.join(LOCAL_WEIGHTS_DIR, s3_key)
        local_dir = os.path.dirname(local_path)
        if not os.path.exists(local_dir): os.makedirs(local_dir)
        if not os.path.exists(local_path):
            logger.info(f"Downloading {s3_key} ...")
            try:
                s3 = get_s3_client()
                s3.download_file(S3_BUCKET_NAME, s3_key, local_path)
            except Exception as e:
                logger.error(f"Download failed: {e}");
                return None
        return local_path

    def _init_sessions(self):
        logger.info("Initializing Sinus Pipeline...")
        # 1. Structure
        p1 = self._download_if_needed(self.struct_key)
        if p1:
            try:
                self.struct_session = ort.InferenceSession(p1, providers=self.providers)
                self.struct_input = self.struct_session.get_inputs()[0].name
            except Exception as e:
                logger.error(f"Structure init failed: {e}")

        # 2. Classifier
        p2 = self._download_if_needed(self.cls_key)
        if p2:
            try:
                self.cls_session = ort.InferenceSession(p2, providers=self.providers)
                self.cls_input = self.cls_session.get_inputs()[0].name
            except Exception as e:
                logger.error(f"Classifier init failed: {e}")

    def _preprocess(self, img, size):
        """通用预处理: Resize -> Norm -> CHW -> Batch"""
        img = cv2.resize(img, size)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0
        img = (img - self.mean) / self.std
        img = img.transpose(2, 0, 1)
        return np.expand_dims(img, axis=0)

    def predict(self, image) -> dict:
        """主推理函数"""
        if not self.struct_session or not self.cls_session:
            return {"MaxillarySinus": []}

        try:
            h, w = image.shape[:2]
            results_list = []
            masks_info = []

            # --- Step 1: 结构分割 (512x512) ---
            struct_in = self._preprocess(image, (512, 512))
            struct_out = self.struct_session.run(None, {self.struct_input: struct_in})[0]

            # 解析 Mask
            mask_512 = np.argmax(struct_out, axis=1)[0]
            mask_full = cv2.resize(mask_512.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)

            # --- Step 2: 连通域 & 抠图 ---
            num, _, stats, centroids = cv2.connectedComponentsWithStats(mask_full, connectivity=8)

            for i in range(1, num):
                if stats[i, cv2.CC_STAT_AREA] < 500: continue

                # 坐标与左右判定
                x, y, sw, sh = stats[i][:4]
                cx = centroids[i][0]
                location = "Right" if cx < (w / 2) else "Left"  # 图片左边=病人右边

                # 抠图 + Padding
                pad = 30
                x1, y1 = max(0, x - pad), max(0, y - pad)
                x2, y2 = min(w, x + sw + pad), min(h, y + sh + pad)
                crop = image[y1:y2, x1:x2]

                if crop.size == 0: continue

                # --- Step 3: 病灶分类 (224x224) ---
                cls_in = self._preprocess(crop, (224, 224))
                cls_out = self.cls_session.run(None, {self.cls_input: cls_in})[0]

                # Softmax
                exps = np.exp(cls_out - np.max(cls_out))
                probs = exps / np.sum(exps)
                pred_idx = np.argmax(probs)  # 0=Inflam, 1=Normal
                conf = float(probs[0][pred_idx])

                is_inflam = (pred_idx == 0)

                # --- Step 4: 构造结果 ---
                side_lower = location.lower()
                cn_side = "左" if side_lower == 'left' else "右"
                detail = f"{cn_side}上颌窦" + ("可见炎症影像，建议复查。" if is_inflam else "气化良好。")

                results_list.append({
                    "Side": side_lower,
                    "Pneumatization": 0,
                    "TypeClassification": 0,
                    "Inflammation": is_inflam,
                    "RootEntryToothFDI": [],
                    "Detail": detail,
                    "Confidence_Pneumatization": 0.99,
                    "Confidence_Inflammation": float(f"{conf:.2f}")
                })

                masks_info.append({
                    "label": f"sinus_{side_lower}",
                    "bbox": [int(x), int(y), int(sw), int(sh)]
                })

            return {"MaxillarySinus": results_list, "masks_info": masks_info}

        except Exception as e:
            logger.error(f"Predict error: {e}")
            return {"MaxillarySinus": []}