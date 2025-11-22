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
        import logging
        logger = logging.getLogger(__name__)
        
        # 1. 解析 Mask
        pred_mask = self._parse_output_to_mask(model_output)
        final_mask = self._resize_mask_to_original(pred_mask)
        logger.info(f"[CondyleSeg postprocess] final_mask shape: {final_mask.shape}")

        # 2. 提取特征
        left_feats = self._extract_features(final_mask, self.CLASS_ID_LEFT)
        right_feats = self._extract_features(final_mask, self.CLASS_ID_RIGHT)
        
        logger.info(f"[CondyleSeg postprocess] Left exists: {left_feats['exists']}, contour points: {len(left_feats.get('contour', []))}")
        logger.info(f"[CondyleSeg postprocess] Right exists: {right_feats['exists']}, contour points: {len(right_feats.get('contour', []))}")

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
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"[_parse_output_to_mask] model_output type: {type(model_output)}")
        
        if isinstance(model_output, torch.Tensor):
            logger.info(f"[_parse_output_to_mask] Tensor shape: {model_output.shape}")
            result = torch.argmax(model_output, dim=1).squeeze(0).cpu().numpy()
            logger.info(f"[_parse_output_to_mask] After argmax result shape: {result.shape}, unique values: {np.unique(result)}")
            return result
        elif isinstance(model_output, np.ndarray):
            logger.info(f"[_parse_output_to_mask] NumPy array shape: {model_output.shape}, ndim: {model_output.ndim}")
            if model_output.ndim == 4:
                result = np.argmax(model_output, axis=1)[0]
                logger.info(f"[_parse_output_to_mask] 4D -> argmax result shape: {result.shape}, unique values: {np.unique(result)}")
                return result
            elif model_output.ndim == 3:
                result = np.argmax(model_output, axis=0)
                logger.info(f"[_parse_output_to_mask] 3D -> argmax result shape: {result.shape}, unique values: {np.unique(result)}")
                return result
            elif model_output.ndim == 2:
                logger.info(f"[_parse_output_to_mask] 2D array, unique values: {np.unique(model_output)}")
                return model_output
            logger.warning(f"[_parse_output_to_mask] Unexpected ndim: {model_output.ndim}")
            return model_output
        
        logger.error(f"[_parse_output_to_mask] Unknown type, returning zeros")
        return np.zeros(self.input_size, dtype=np.uint8)

    def _resize_mask_to_original(self, mask):
        mask = mask.astype(np.uint8)
        return cv2.resize(mask, (int(self.orig_w), int(self.orig_h)), interpolation=cv2.INTER_NEAREST)

    def _extract_features(self, mask, class_id):
        """提取特征，包括面积、置信度和轮廓"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"[_extract_features] class_id={class_id}, mask shape={mask.shape}, mask unique values: {np.unique(mask)}")
        
        binary_mask = (mask == class_id).astype(np.uint8)
        area = np.sum(binary_mask)
        
        logger.info(f"[_extract_features] class_id={class_id}, binary_mask sum (area)={area}")
        
        if area == 0:
            return {
                "area": 0,
                "exists": False,
                "confidence": 0.0,
                "contour": [],
                "mask": None
            }
        
        # 提取轮廓
        contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # 取最大轮廓
        contour_coords = []
        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            # 转换为 [[x, y], [x, y], ...] 格式
            contour_coords = largest_contour.squeeze().tolist()
            # 确保是二维列表
            if contour_coords and not isinstance(contour_coords[0], list):
                contour_coords = [contour_coords]
        
        # 模拟置信度
        confidence = 0.95
        
        return {
            "area": int(area),
            "exists": True,
            "confidence": confidence,
            "contour": contour_coords,
            "mask": binary_mask
        }