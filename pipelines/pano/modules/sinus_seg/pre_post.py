# -*- coding: utf-8 -*-
"""
上颌窦（Sinus）全流程前后处理
逻辑链条：
1. preprocess: 全景片 -> 512x512 -> 结构分割模型
2. post_crop: 分割Mask -> 连通域分析 -> 左右定位 -> 抠出小图
3. prep_classifier: 小图 -> 224x224 -> 病灶分类模型
"""

import cv2
import numpy as np
import torch
from PIL import Image


class SinusPrePostProcessor:
    """
    上颌窦智能诊断处理器
    """

    def __init__(self, seg_size=(512, 512), cls_size=(224, 224)):
        # 阶段1：结构分割模型的输入尺寸
        self.seg_size = seg_size
        # 阶段2：病灶分类模型的输入尺寸
        self.cls_size = cls_size

        # 归一化参数 (ImageNet 标准)
        self.MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        self.STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def preprocess_segmentation(self, image: np.ndarray) -> torch.Tensor:
        """
        Step 1: 为【结构分割模型】准备输入
        Input: 原始大图 (H, W, 3)
        Output: Tensor (1, 3, 512, 512)
        """
        # 记录原始尺寸，用于后续还原 Mask
        self.orig_h, self.orig_w = image.shape[:2]

        # Resize 到 512
        img = cv2.resize(image, self.seg_size)

        # 归一化
        img = img.astype(np.float32) / 255.0
        img = (img - self.MEAN) / self.STD

        # HWC -> CHW -> Batch
        img = img.transpose(2, 0, 1)
        return torch.from_numpy(img).unsqueeze(0)

    def process_segmentation_result(self, seg_output, original_image, pad=20):
        """
        Step 2: 处理分割结果，抠出上颌窦小图
        Input:
            seg_output: 结构模型的输出 (Logits 或 Argmax)
            original_image: 原始大图 (用于抠图)
            pad: 抠图时的边缘扩充像素
        Output:
            crops_info: 列表，包含 [{'crop': 图片, 'location': 'Left', 'bbox': ...}, ...]
        """
        # 1. 解析 Mask
        pred_mask = self._parse_output_to_mask(seg_output)

        # 2. 还原回原图尺寸 (重要！否则坐标不对)
        mask_full = cv2.resize(pred_mask.astype(np.uint8), (self.orig_w, self.orig_h), interpolation=cv2.INTER_NEAREST)

        # 3. 连通域分析 (区分左右上颌窦)
        # connectivity=8 表示8连通
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask_full, connectivity=8)

        crops_info = []

        # 遍历所有连通域 (label=0 是背景，跳过)
        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]

            # 过滤噪点：太小的区域不要
            if area < 500: continue

            # 获取位置信息
            x = stats[i, cv2.CC_STAT_LEFT]
            y = stats[i, cv2.CC_STAT_TOP]
            w = stats[i, cv2.CC_STAT_WIDTH]
            h = stats[i, cv2.CC_STAT_HEIGHT]
            cx = centroids[i][0]  # 质心X坐标

            # --- 核心逻辑：判断左右 ---
            # 医学影像通常是镜像的：图片左边 = 病人右侧
            location = "Right" if cx < (self.orig_w / 2) else "Left"

            # --- 抠图 ---
            # 加上 padding 防止切坏边缘
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(self.orig_w, x + w + pad)
            y2 = min(self.orig_h, y + h + pad)

            # 从原图切片
            crop_img = original_image[y1:y2, x1:x2]

            # 保存信息供下一步使用
            crops_info.append({
                "crop": crop_img,  # 用于分类的小图
                "location": location,  # 左右方位
                "bbox": [x, y, w, h],  # 原始坐标
                "bbox_pad": [x1, y1, x2, y2]  # 带padding的坐标
            })

        # 按位置排序：保证输出顺序是先右后左 (Right -> Left)
        # 这里用 x 坐标排序：x小的在左边(Right)，x大的在右边(Left)
        crops_info.sort(key=lambda k: k['bbox'][0])

        return crops_info

    def preprocess_classifier(self, crop_image: np.ndarray) -> torch.Tensor:
        """
        Step 3: 为【病灶分类模型】准备输入
        Input: 上一步抠出来的小图 (H', W', 3)
        Output: Tensor (1, 3, 224, 224)
        """
        if crop_image is None or crop_image.size == 0:
            return None

        # Resize 到 224
        img = cv2.resize(crop_image, self.cls_size)

        # 归一化
        img = img.astype(np.float32) / 255.0
        img = (img - self.MEAN) / self.STD

        # HWC -> CHW -> Batch
        img = img.transpose(2, 0, 1)
        return torch.from_numpy(img).unsqueeze(0)

    def interpret_diagnosis(self, cls_output):
        """
        Step 4: 解析分类结果
        Input: 分类模型输出 (Logits)
        Output: (diagnosis_str, is_inflam, confidence)
        """
        # 兼容 Tensor 和 Numpy/ONNX
        if isinstance(cls_output, np.ndarray):
            cls_output = torch.from_numpy(cls_output)

        probs = torch.softmax(cls_output, dim=1)
        pred_idx = torch.argmax(probs, dim=1).item()
        conf = probs[0][pred_idx].item()

        # 映射逻辑 (必须与训练时 ImageFolder 顺序一致)
        # 0: Inflam (炎症)
        # 1: Normal (正常)

        is_inflam = (pred_idx == 0)
        diagnosis = "Inflammation" if is_inflam else "Normal"

        return diagnosis, is_inflam, conf

    def _parse_output_to_mask(self, model_output):
        """工具：将模型输出转为 mask"""
        if isinstance(model_output, torch.Tensor):
            return torch.argmax(model_output, dim=1).squeeze(0).cpu().numpy()
        elif isinstance(model_output, np.ndarray):
            # ONNX 输出: (1, 2, 512, 512) -> argmax -> (1, 512, 512)
            if model_output.ndim == 4:
                return np.argmax(model_output, axis=1)[0]
            # ONNX 输出: (1, 512, 512)
            elif model_output.ndim == 3:
                return model_output[0]
            return model_output
        return np.zeros(self.seg_size, dtype=np.uint8)


# ================= 使用示例 =================
if __name__ == "__main__":
    # 模拟数据
    processor = SinusPrePostProcessor()
    dummy_img = np.random.randint(0, 255, (1000, 2000, 3), dtype=np.uint8)

    # 1. 结构模型预处理
    seg_input = processor.preprocess_segmentation(dummy_img)
    print(f"Seg Input Shape: {seg_input.shape}")  # Should be (1, 3, 512, 512)

    # ... 假设这里运行了 ONNX/PyTorch 得到了结构模型输出 seg_out ...
    # 模拟一个 Mask：左边(病人右)有个上颌窦，右边(病人左)有个上颌窦
    dummy_mask_out = np.zeros((1, 2, 512, 512), dtype=np.float32)
    dummy_mask_out[0, 1, 100:200, 50:150] = 10  # 假装置信度高
    dummy_mask_out[0, 1, 100:200, 400:500] = 10

    # 2. 处理分割结果，得到截图
    crops = processor.process_segmentation_result(dummy_mask_out, dummy_img)
    print(f"Detected Sinuses: {len(crops)}")

    for c in crops:
        print(f"  -> Location: {c['location']}, Crop Size: {c['crop'].shape}")

        # 3. 分类模型预处理
        cls_input = processor.preprocess_classifier(c['crop'])
        print(f"     Class Input Shape: {cls_input.shape}")  # Should be (1, 3, 224, 224)

        # ... 假设运行分类模型得到 cls_out ...
        dummy_cls_out = torch.tensor([[5.0, -1.0]])  # 模拟预测 Inflam(0)

        # 4. 解析诊断
        diag, is_inf, conf = processor.interpret_diagnosis(dummy_cls_out)
        print(f"     Diagnosis: {diag} ({conf:.2f})")