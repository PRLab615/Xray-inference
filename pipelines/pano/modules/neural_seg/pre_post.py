# -*- coding: utf-8 -*-
import cv2
import numpy as np
import torch
import logging


class NeuralPrePostProcessor:
    def __init__(self, input_size=(224, 224)):
        self.input_size = input_size
        # 保持与参考代码一致的 ID 定义：人为规定 1=左侧, 2=右侧
        self.CLASS_ID_LEFT = 1
        self.CLASS_ID_RIGHT = 2

    def preprocess(self, image: np.ndarray) -> torch.Tensor:
        """
        [预处理] 完全复用参考逻辑
        """
        self.orig_h, self.orig_w = image.shape[:2]
        img_resized = cv2.resize(image, self.input_size)
        # 保持参考代码的归一化方式: x/255.0
        img_float = img_resized.astype(np.float32) / 255.0
        img_chw = img_float.transpose(2, 0, 1)
        return torch.from_numpy(img_chw).unsqueeze(0)

    def postprocess(self, model_output) -> dict:
        """
        [后处理] 流程与参考代码完全一致，不改动任何接口逻辑
        """
        logger = logging.getLogger(__name__)

        # 1. 解析 Mask
        # 【关键点】在这里把二分类结果变成伪多分类 (0/1 -> 0/1/2)
        pred_mask = self._parse_output_to_mask(model_output)

        # 2. 还原尺寸
        final_mask = self._resize_mask_to_original(pred_mask)
        logger.info(f"[NeuralSeg] final_mask shape: {final_mask.shape}, unique values: {np.unique(final_mask)}")

        # 3. 提取特征 (此时 final_mask 里已经有 1 和 2 了，所以这里能取到)
        left_feats = self._extract_features(final_mask, self.CLASS_ID_LEFT)
        right_feats = self._extract_features(final_mask, self.CLASS_ID_RIGHT)

        logger.info(f"[NeuralSeg] Left detected: {left_feats['exists']}, Right detected: {right_feats['exists']}")

        # 4. 计算指标
        analysis_result = self._analyze_symmetry(left_feats, right_feats)

        # 5. 返回结构保持不变
        return {
            "mask_shape": final_mask.shape,
            "raw_features": {
                "left": left_feats,
                "right": right_feats
            },
            "analysis": analysis_result
        }

    def _parse_output_to_mask(self, model_output):
        """
        【核心修改区域】
        将模型的"二分类输出" (0,1) 转换为下游需要的"左右ID" (0,1,2)
        """
        logger = logging.getLogger(__name__)

        # --- A. 先获取纯净的二值 Mask (0/1) ---
        binary_mask = None

        # 1. 处理 Tensor
        if isinstance(model_output, torch.Tensor):
            if model_output.ndim == 4:  # (B, C, H, W)
                if model_output.shape[1] == 2:  # 比如 (1, 2, 224, 224) Logits
                    binary_mask = torch.argmax(model_output, dim=1).squeeze(0).cpu().numpy()
                else:  # 比如 (1, 1, 224, 224) Sigmoid
                    binary_mask = (model_output > 0.5).int().squeeze(0).cpu().numpy()
            elif model_output.ndim == 3:
                binary_mask = torch.argmax(model_output, dim=0).cpu().numpy()

        # 2. 处理 Numpy (ONNX Runtime 输出)
        elif isinstance(model_output, np.ndarray):
            if model_output.ndim == 4:
                if model_output.shape[1] == 2:
                    binary_mask = np.argmax(model_output, axis=1)[0]
                else:
                    binary_mask = (model_output[0, 0] > 0.5).astype(np.uint8)
            elif model_output.ndim == 3:
                # 假设是 (C, H, W)
                binary_mask = np.argmax(model_output, axis=0) if model_output.shape[0] > 1 else (
                            model_output[0] > 0.5).astype(np.uint8)
            else:
                binary_mask = model_output

        # 兜底
        if binary_mask is None:
            return np.zeros(self.input_size, dtype=np.uint8)

        # 确保是二值的 (0/1)
        binary_mask = (binary_mask > 0).astype(np.uint8)

        # --- B. 执行左右分离 (连通域分析) ---
        # 这一步就是您要的"通过后处理分成两块"
        labeled_output = np.zeros_like(binary_mask, dtype=np.uint8)

        # 连通域分析
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary_mask, connectivity=8)

        # 图像中线
        center_x_threshold = binary_mask.shape[1] // 2

        for i in range(1, num_labels):  # 0是背景，跳过
            area = stats[i, cv2.CC_STAT_AREA]
            if area < 30:  # 忽略极小噪点
                continue

            c_x = centroids[i][0]

            # 【重点】根据位置强行赋值 ID
            # 这里的 CLASS_ID_LEFT=1, CLASS_ID_RIGHT=2
            # 这样下游的 _extract_features(mask, 1) 就能取到左边了
            if c_x < center_x_threshold:
                labeled_output[labels == i] = self.CLASS_ID_LEFT
            else:
                labeled_output[labels == i] = self.CLASS_ID_RIGHT

        return labeled_output

    def _resize_mask_to_original(self, mask):
        """复用参考逻辑: 最近邻插值"""
        mask = mask.astype(np.uint8)
        return cv2.resize(mask, (int(self.orig_w), int(self.orig_h)), interpolation=cv2.INTER_NEAREST)

    def _extract_features(self, mask, class_id):
        """复用参考逻辑: 提取特定ID的特征"""

        # 这里的 mask 已经是我们加工过的 0/1/2 Mask 了
        # 所以 mask == 1 取出左边，mask == 2 取出右边
        binary_mask = (mask == class_id).astype(np.uint8)
        area = np.sum(binary_mask)

        if area == 0:
            return {
                "area": 0, "exists": False, "confidence": 0.0, "contour": [], "mask": None
            }

        # 提取轮廓
        contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        contour_coords = []
        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            # 转为 list
            contour_coords = largest_contour.squeeze().tolist()
            if contour_coords and not isinstance(contour_coords[0], list):
                contour_coords = [contour_coords]

        return {
            "area": int(area),
            "exists": True,
            "confidence": 0.95,  # 模拟置信度
            "contour": contour_coords,
            "mask": binary_mask
        }

    def _analyze_symmetry(self, left: dict, right: dict) -> dict:
        """复用参考逻辑: 计算对称性"""
        if not left["exists"] or not right["exists"]:
            return {"is_symmetric": False, "conclusion": "检测不全", "metrics": {}}

        area_l = left["area"]
        area_r = right["area"]

        # 防止除0
        avg = (area_l + area_r) / 2.0
        if avg < 1e-5:
            area_diff = 0
        else:
            area_diff = abs(area_l - area_r) / avg * 100

        # 神经管可能比髁突更细长，差异阈值可根据实际情况微调
        is_symmetric = area_diff < 15.0
        conclusion = "正常" if is_symmetric else f"差异显著({area_diff:.1f}%)"

        return {
            "is_symmetric": is_symmetric,
            "conclusion": conclusion,
            "metrics": {
                "area_diff_percent": area_diff,
                "left_area": area_l,
                "right_area": area_r
            }
        }