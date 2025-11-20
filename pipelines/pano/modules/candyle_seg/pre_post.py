# -*- coding: utf-8 -*-
import cv2
import numpy as np
import torch


class JointPrePostProcessor:
    def __init__(self, input_size=(224, 224)):
        self.input_size = input_size
        self.CLASS_ID_LEFT = 1
        self.CLASS_ID_RIGHT = 2

    def preprocess(self, image: np.ndarray) -> torch.Tensor:
        """图像预处理"""
        self.orig_h, self.orig_w = image.shape[:2]
        img_resized = cv2.resize(image, self.input_size)
        img_float = img_resized.astype(np.float32) / 255.0
        img_chw = img_float.transpose(2, 0, 1)
        return torch.from_numpy(img_chw).unsqueeze(0)

    def postprocess(self, model_output) -> dict:
        """
        后处理: 返回纯粹的几何特征和分析指标
        不再返回 standard_data，只返回 raw data
        """
        # 1. 解析 Mask
        pred_mask = self._parse_output_to_mask(model_output)
        final_mask = self._resize_mask_to_original(pred_mask)

        # 2. 提取特征
        left_feats = self._extract_features(final_mask, self.CLASS_ID_LEFT)
        right_feats = self._extract_features(final_mask, self.CLASS_ID_RIGHT)

        # 3. 计算对称性指标
        analysis_result = self._analyze_symmetry(left_feats, right_feats)

        # 返回纯净的中间数据
        return {
            "mask_shape": final_mask.shape,
            "raw_features": {
                "left": left_feats,
                "right": right_feats
            },
            "analysis": analysis_result
        }

    # ... (保留 _parse_output_to_mask, _resize_mask_to_original, _extract_features 等辅助函数)
    # ... (保留 _extract_features 里的 confidence 逻辑)

    def _analyze_symmetry(self, left: dict, right: dict) -> dict:
        """计算具体的数学指标"""
        if not left["exists"] or not right["exists"]:
            return {"is_symmetric": False, "conclusion": "检测不全", "metrics": {}}

        area_l = left["area"]
        area_r = right["area"]

        # 计算差异百分比
        area_diff = abs(area_l - area_r) / ((area_l + area_r) / 2 + 1e-5) * 100

        is_symmetric = area_diff < 15.0

        conclusion = "正常"
        if not is_symmetric:
            conclusion = f"面积差异显著({area_diff:.1f}%)"

        return {
            "is_symmetric": is_symmetric,
            "conclusion": conclusion,
            "metrics": {
                "area_diff_percent": area_diff,
                "left_area": area_l,
                "right_area": area_r
            }
        }

    # ... (其他辅助函数)

    def _parse_output_to_mask(self, model_output):
        """兼容处理 Tensor 和 Numpy 的 Argmax"""
        if isinstance(model_output, torch.Tensor):
            return torch.argmax(model_output, dim=1).squeeze(0).cpu().numpy()
        elif isinstance(model_output, np.ndarray):
            if model_output.ndim == 4:
                return np.argmax(model_output, axis=1)[0]
            elif model_output.ndim == 3:
                return np.argmax(model_output, axis=0)
            return model_output
        return np.zeros(self.input_size, dtype=np.uint8)

    def _resize_mask_to_original(self, mask):
        mask = mask.astype(np.uint8)
        return cv2.resize(mask, (int(self.orig_w), int(self.orig_h)), interpolation=cv2.INTER_NEAREST)

    def _extract_features(self, mask, class_id):
        binary_mask = (mask == class_id).astype(np.uint8)
        area = np.sum(binary_mask)
        if area == 0:
            return {"area": 0, "exists": False, "confidence": 0.0}
        # 模拟置信度
        return {"area": int(area), "exists": True, "confidence": 0.95}