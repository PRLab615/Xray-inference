# -*- coding: utf-8 -*-
"""
下颌骨（Mandible）分割前后处理
包含核心的对称性判定逻辑 (移植自 inference_symmetry_final.py)
"""

import cv2
import numpy as np
import torch


class MandiblePrePostProcessor:
    """
    下颌骨分割前后处理类
    负责图像标准化和基于几何形态的对称性分析
    """

    def __init__(self, input_size=(224, 224)):
        self.input_size = input_size

        # 类别定义 (0:背景, 1:左, 2:右)
        self.CLASS_ID_LEFT = 1
        self.CLASS_ID_RIGHT = 2

        # ================= 移植原脚本的阈值设置 =================
        # 1. 面积容忍度 (允许相差 25% 以内)
        self.TH_AREA_RATIO = 1.25
        # 2. 高度容忍度 (允许垂直高度相差 15% 以内)
        self.TH_HEIGHT_RATIO = 1.15
        # 3. 形状容忍度 (允许长宽比相差 0.2 以内)
        self.TH_AR_DIFF = 0.2

        # 归一化参数 (ImageNet 标准，与你原脚本对应)
        self.MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        self.STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def preprocess(self, image: np.ndarray) -> torch.Tensor:
        """
        图像预处理
        Logic: Resize -> Normalize(Mean/Std) -> HWC2CHW -> Batch
        """
        # 记录原始尺寸
        self.orig_h, self.orig_w = image.shape[:2]

        # 1. Resize
        img = cv2.resize(image, self.input_size)

        # 2. Normalize (归一化到 0-1 并减去均值除以方差)
        img = img.astype(np.float32) / 255.0
        img = (img - self.MEAN) / self.STD

        # 3. Transpose (HWC -> CHW)
        img = img.transpose(2, 0, 1)

        # 4. Add Batch Dim
        return torch.from_numpy(img).unsqueeze(0)

    def postprocess(self, model_output) -> dict:
        """
        后处理主入口
        Args:
            model_output: 模型输出 (Logits 或 Argmax)
        Returns:
            dict: 包含分析结果和原始特征
        """
        # 1. 解析输出为 Mask
        pred_mask = self._parse_output_to_mask(model_output)

        # 2. 还原 Mask 到原图尺寸 (可选，为了计算真实的像素值建议还原)
        # 如果不需要原图尺寸的像素值，也可以直接用 224x224 的 mask 计算，比例是一样的
        final_mask = self._resize_mask_to_original(pred_mask)

        # 3. 执行核心对称性逻辑 (原 is_symmetric 函数)
        is_sym, detail_str, metrics = self._is_symmetric(final_mask)

        # 4. 包装结果
        # 注意：这里返回的结构是为了配合 Predictor 使用
        return {
            "mask_shape": final_mask.shape,
            "analysis": {
                "RamusSymmetry": is_sym,  # 升支对称性 (整体对称性)
                "GonialAngleSymmetry": is_sym,  # 下颌角对称性 (暂复用整体结果，也可拆分)
                "Detail": detail_str,
                "Confidence": 1.0 if is_sym else 0.8,  # 简单模拟置信度
                "Metrics": metrics
            }
        }

    def _get_bbox_stats(self, mask_binary):
        """
        移植自原脚本: get_bbox_stats
        计算二值掩码的面积、高、宽、长宽比
        """
        if np.sum(mask_binary) == 0:
            return 0, 0, 0, 0, None

        rows = np.any(mask_binary, axis=1)
        cols = np.any(mask_binary, axis=0)
        y1, y2 = np.where(rows)[0][[0, -1]]
        x1, x2 = np.where(cols)[0][[0, -1]]

        h = y2 - y1
        w = x2 - x1
        area = np.sum(mask_binary)
        ar = h / (w + 1e-5)  # Aspect Ratio

        return area, h, w, ar, (y1, x1, y2, x2)

    def _is_symmetric(self, pred_mask):
        """
        移植自原脚本: is_symmetric
        严格判断逻辑：返回 (Bool, String, Metrics)
        """
        # 1. 分离左右
        mask_l = (pred_mask == self.CLASS_ID_LEFT)
        mask_r = (pred_mask == self.CLASS_ID_RIGHT)

        # 2. 计算指标
        area_l, h_l, w_l, ar_l, _ = self._get_bbox_stats(mask_l)
        area_r, h_r, w_r, ar_r, _ = self._get_bbox_stats(mask_r)

        # 收集指标用于 Debug 或高级分析
        metrics = {
            "area_l": int(area_l), "area_r": int(area_r),
            "h_l": int(h_l), "h_r": int(h_r),
            "ar_l": float(ar_l), "ar_r": float(ar_r)
        }

        # --- 判定条件 1: 是否缺失 ---
        if area_l == 0 or area_r == 0:
            return False, "false (单侧缺失)", metrics

        # --- 判定条件 2: 面积 (相差不大) ---
        area_ratio = max(area_l, area_r) / (min(area_l, area_r) + 1e-5)
        if area_ratio > self.TH_AREA_RATIO:
            return False, f"false (面积差异过大: {area_ratio:.2f}倍)", metrics

        # --- 判定条件 3: 高度 (形态一致性 - 纵向) ---
        h_ratio = max(h_l, h_r) / (min(h_l, h_r) + 1e-5)
        if h_ratio > self.TH_HEIGHT_RATIO:
            return False, f"false (高度差异过大: {h_ratio:.2f}倍)", metrics

        # --- 判定条件 4: 长宽比 (形态一致性 - 整体形状) ---
        ar_diff = abs(ar_l - ar_r)
        if ar_diff > self.TH_AR_DIFF:
            return False, f"false (形状差异过大: AR差 {ar_diff:.2f})", metrics

        # 只有全部通过，才返回 True
        return True, "true (对称)", metrics

    def _parse_output_to_mask(self, model_output):
        """兼容 Tensor 和 Numpy 的处理"""
        if isinstance(model_output, torch.Tensor):
            return torch.argmax(model_output, dim=1).squeeze(0).cpu().numpy()
        elif isinstance(model_output, np.ndarray):
            # ONNX 输出通常是 (1, C, H, W) -> argmax -> (1, H, W)
            if model_output.ndim == 4:
                return np.argmax(model_output, axis=1)[0]
            elif model_output.ndim == 3:
                return np.argmax(model_output, axis=0)
            return model_output
        return np.zeros(self.input_size, dtype=np.uint8)

    def _resize_mask_to_original(self, mask):
        """将 Mask 还原回原图尺寸"""
        mask = mask.astype(np.uint8)
        return cv2.resize(mask, (int(self.orig_w), int(self.orig_h)), interpolation=cv2.INTER_NEAREST)