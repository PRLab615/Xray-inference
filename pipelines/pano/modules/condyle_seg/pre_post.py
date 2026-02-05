# -*- coding: utf-8 -*-
import cv2
import numpy as np
import torch
import logging
from ..contour_smooth_utils import smooth_contour_by_preset


class JointPrePostProcessor:
    def __init__(self, input_size=(224, 224)):
        self.input_size = input_size
        # 保持您原有的 ID 定义：1=Left, 2=Right
        self.CLASS_ID_LEFT = 1
        self.CLASS_ID_RIGHT = 2

    def preprocess(self, image: np.ndarray) -> torch.Tensor:
        """图像预处理 (保持不变)"""
        self.orig_h, self.orig_w = image.shape[:2]
        img_resized = cv2.resize(image, self.input_size)
        img_float = img_resized.astype(np.float32) / 255.0
        img_chw = img_float.transpose(2, 0, 1)
        return torch.from_numpy(img_chw).unsqueeze(0)

    def postprocess(self, model_output) -> dict:
        """
        后处理 (接口逻辑保持不变)
        """
        logger = logging.getLogger(__name__)

        # 1. 解析 Mask
        # 【关键修改】在这里把二值 Mask (0/1) 变成了 左右分离 Mask (0/1/2)
        pred_mask = self._parse_output_to_mask(model_output)

        # 2. 还原尺寸
        final_mask = self._resize_mask_to_original(pred_mask)
        logger.info(f"[CondyleSeg] final_mask shape: {final_mask.shape}, unique values: {np.unique(final_mask)}")

        # 3. 提取特征 (现在 final_mask 里有 1 和 2 了，所以能提取到了)
        left_feats = self._extract_features(final_mask, self.CLASS_ID_LEFT)
        right_feats = self._extract_features(final_mask, self.CLASS_ID_RIGHT)

        logger.info(
            f"[CondyleSeg] Left exists: {left_feats['exists']}, contour points: {len(left_feats.get('contour', []))}")
        logger.info(
            f"[CondyleSeg] Right exists: {right_feats['exists']}, contour points: {len(right_feats.get('contour', []))}")

        # 4. 计算对称性指标
        analysis_result = self._analyze_symmetry(left_feats, right_feats)

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
        兼容处理 Tensor/Numpy，并执行 '二值 -> 左右分离' 的逻辑
        """
        logger = logging.getLogger(__name__)

        # --- A. 获取纯净的二值 Mask (0/1) ---
        binary_mask = None

        if isinstance(model_output, torch.Tensor):
            # 处理 Tensor (1, C, H, W)
            if model_output.ndim == 4:
                if model_output.shape[1] == 2:  # Argmax
                    binary_mask = torch.argmax(model_output, dim=1).squeeze(0).cpu().numpy()
                else:  # Sigmoid
                    binary_mask = (model_output > 0.5).int().squeeze(0).cpu().numpy()
            elif model_output.ndim == 3:
                binary_mask = torch.argmax(model_output, dim=0).cpu().numpy()

        elif isinstance(model_output, np.ndarray):
            # 处理 Numpy (ONNX输出)
            if model_output.ndim == 4:
                if model_output.shape[1] == 2:
                    binary_mask = np.argmax(model_output, axis=1)[0]
                else:
                    binary_mask = (model_output[0, 0] > 0.5).astype(np.uint8)
            elif model_output.ndim == 3:
                binary_mask = np.argmax(model_output, axis=0) if model_output.shape[0] > 1 else (
                            model_output[0] > 0.5).astype(np.uint8)
            else:
                binary_mask = model_output

        # 兜底：如果解析失败，返回全黑
        if binary_mask is None:
            logger.error("Unknown output format, returning zeros")
            return np.zeros(self.input_size, dtype=np.uint8)

        # 确保是 0/1 二值图
        binary_mask = (binary_mask > 0).astype(np.uint8)

        # --- B. 执行左右分离 (连通域分析) ---
        # 如果模型已经是多分类的(比如已经有2了)，就不处理
        if np.max(binary_mask) > 1:
            return binary_mask

        labeled_output = np.zeros_like(binary_mask, dtype=np.uint8)

        # 1. 连通域分析
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary_mask, connectivity=8)

        # 2. 图像中线
        center_x_threshold = binary_mask.shape[1] // 2

        # 3. 遍历每个块，根据位置强行赋 ID
        for i in range(1, num_labels):  # 0是背景，跳过
            area = stats[i, cv2.CC_STAT_AREA]
            if area < 50:  # 忽略极小噪点
                continue

            c_x = centroids[i][0]

            # 判断在左边还是右边
            if c_x < center_x_threshold:
                # 图像左侧 -> 赋值为 CLASS_ID_LEFT (1)
                labeled_output[labels == i] = self.CLASS_ID_LEFT
            else:
                # 图像右侧 -> 赋值为 CLASS_ID_RIGHT (2)
                labeled_output[labels == i] = self.CLASS_ID_RIGHT

        return labeled_output

    def _resize_mask_to_original(self, mask):
        """(保持不变) 使用最近邻插值，防止 ID 1 和 2 混合变成 1.5"""
        mask = mask.astype(np.uint8)
        return cv2.resize(mask, (int(self.orig_w), int(self.orig_h)), interpolation=cv2.INTER_NEAREST)

    def _extract_features(self, mask, class_id):
        """(保持不变) 根据 class_id 提取特征"""
        logger = logging.getLogger(__name__)

        # 这里 mask == class_id 会分别取到 1 和 2
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
            # 转换为标准格式 [[x,y], [x,y], ...]
            contour_coords = largest_contour.squeeze().tolist()
            if contour_coords and not isinstance(contour_coords[0], list):
                contour_coords = [contour_coords]
            
            # [NEW] 应用平滑处理（迁移自前端）
            # 使用 aggressive 模式：滑动平均 + RDP抽稀 + Chaikin平滑
            if contour_coords and len(contour_coords) >= 3:
                contour_coords = smooth_contour_by_preset(contour_coords, "condyle")

        return {
            "area": int(area),
            "exists": True,
            "confidence": 0.95,
            "contour": contour_coords,  # 输出标准格式：[[x,y], [x,y], ...]
            "mask": binary_mask
        }

    def _analyze_symmetry(self, left: dict, right: dict) -> dict:
        """(保持不变) 计算对称性"""
        if not left["exists"] or not right["exists"]:
            return {"is_symmetric": False, "conclusion": "检测不全", "metrics": {}}

        area_l = left["area"]
        area_r = right["area"]

        avg = (area_l + area_r) / 2.0
        if avg < 1e-5:
            area_diff = 0
        else:
            area_diff = abs(area_l - area_r) / avg * 100

        is_symmetric = area_diff < 15.0
        conclusion = "正常" if is_symmetric else f"面积差异显著({area_diff:.1f}%)"

        return {
            "is_symmetric": is_symmetric,
            "conclusion": conclusion,
            "metrics": {
                "area_diff_percent": area_diff,
                "left_area": area_l,
                "right_area": area_r
            }
        }