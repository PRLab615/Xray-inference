# -*- coding: utf-8 -*-
import cv2
import numpy as np
import torch
import logging


class SinusPrePostProcessor:
    def __init__(self, seg_size=(512, 512), cls_size=(224, 224)):
        self.logger = logging.getLogger(__name__)
        self.seg_size = seg_size
        self.cls_size = cls_size
        self.MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        self.STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def preprocess_segmentation(self, image: np.ndarray) -> torch.Tensor:
        if image is None: raise ValueError("Input image is None")
        self.orig_h, self.orig_w = image.shape[:2]
        img = cv2.resize(image, self.seg_size)
        img = img.astype(np.float32) / 255.0
        img = (img - self.MEAN) / self.STD
        img = img.transpose(2, 0, 1)
        return torch.from_numpy(img).unsqueeze(0)

    def process_segmentation_result(self, seg_output, original_image, pad=20):
        """
        处理分割结果，返回：左右位置、抠图、以及【轮廓坐标】
        """
        # 1. 解析并还原 Mask
        pred_mask_small = self._parse_output_to_mask(seg_output)
        mask_full = cv2.resize(pred_mask_small.astype(np.uint8), (self.orig_w, self.orig_h),
                               interpolation=cv2.INTER_NEAREST)

        # 2. 连通域分析
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask_full, connectivity=8)
        crops_info = []

        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            if area < 1000: continue  # 过滤噪点

            # 获取位置
            x, y, w, h = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP], stats[i, cv2.CC_STAT_WIDTH], stats[
                i, cv2.CC_STAT_HEIGHT]
            cx = centroids[i][0]

            # 判断左右 (图左=右侧)
            location = "Right" if cx < (self.orig_w / 2) else "Left"

            # --- 核心新增：提取精细轮廓 ---
            # 提取当前连通域的独立 mask
            component_mask = (labels == i).astype(np.uint8)
            contours, _ = cv2.findContours(component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            contour_points = []
            if contours:
                largest = max(contours, key=cv2.contourArea)
                # 稀疏化轮廓点，减少 JSON 体积 (epsilon 可调)
                epsilon = 0.002 * cv2.arcLength(largest, True)
                approx = cv2.approxPolyDP(largest, epsilon, True)
                # 转换为标准 Python list [[x,y], [x,y]...]
                contour_points = approx.squeeze().tolist()
                if not isinstance(contour_points[0], list):  # 处理只有一个点的情况
                    contour_points = [contour_points]

            # 抠图
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(self.orig_w, x + w + pad)
            y2 = min(self.orig_h, y + h + pad)
            crop_img = original_image[y1:y2, x1:x2]

            if crop_img.size == 0: continue

            crops_info.append({
                "crop": crop_img,
                "location": location,
                "bbox": [int(x), int(y), int(w), int(h)],  # 强制转 int
                "contour": contour_points  # 包含轮廓数据
            })

        # 按位置排序 (从图左到图右)
        crops_info.sort(key=lambda k: k['bbox'][0])
        return crops_info

    def preprocess_classifier(self, crop_image: np.ndarray) -> torch.Tensor:
        if crop_image is None or crop_image.size == 0: return None
        img = cv2.resize(crop_image, self.cls_size)
        img = img.astype(np.float32) / 255.0
        img = (img - self.MEAN) / self.STD
        img = img.transpose(2, 0, 1)
        return torch.from_numpy(img).unsqueeze(0)

    def _parse_output_to_mask(self, model_output):
        if isinstance(model_output, torch.Tensor):
            if model_output.ndim == 4:
                return torch.argmax(model_output, dim=1).squeeze(0).cpu().numpy() if model_output.shape[1] == 2 else (
                            model_output > 0.5).long().squeeze(0).cpu().numpy()
            elif model_output.ndim == 3:
                return torch.argmax(model_output, dim=0).cpu().numpy()
        elif isinstance(model_output, np.ndarray):
            if model_output.ndim == 4:
                return np.argmax(model_output, axis=1)[0]
            elif model_output.ndim == 3:
                return np.argmax(model_output, axis=0)
            return model_output
        return np.zeros(self.seg_size, dtype=np.uint8)

    # 保留辅助函数以兼容 pipeline 调用
    def _extract_tooth_apex_positions(self, *args, **kwargs):
        return {}