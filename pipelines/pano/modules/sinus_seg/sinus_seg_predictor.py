# -*- coding: utf-8 -*-
import os
import sys
import logging
import cv2
import numpy as np
import onnxruntime as ort

# --- 1. 引用工具 ---
sys.path.append(os.getcwd())
from tools.load_weight import get_s3_client, S3_BUCKET_NAME, LOCAL_WEIGHTS_DIR

# --- 2. 引用前处理 ---
from pipelines.pano.modules.sinus_seg.pre_post import SinusPrePostProcessor

logger = logging.getLogger(__name__)


class SinusStructurePredictor:
    """
    上颌窦结构分割推理器 (仅分割，不分类)

    Input:  原始图片 (H, W, 3)
    Output: 原始尺寸的 Mask (H, W) 及 轮廓信息
    """

    def __init__(self):
        # 优先 GPU
        self.providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']

        # --- 配置: 结构分割模型路径 ---
        self.onnx_key = "weights/panoramic/sinus_structure_resnetunet.onnx"

        # 实例化前处理 (只用到 seg_size=512)
        self.processor = SinusPrePostProcessor(seg_size=(512, 512))

        self.session = None
        self._init_session()

    def _download_if_needed(self, s3_key):
        """下载权重"""
        local_path = os.path.join(LOCAL_WEIGHTS_DIR, s3_key)
        local_dir = os.path.dirname(local_path)
        if not os.path.exists(local_dir): os.makedirs(local_dir)

        if not os.path.exists(local_path):
            logger.info(f"Downloading Structure model: {s3_key} ...")
            try:
                s3 = get_s3_client()
                s3.download_file(S3_BUCKET_NAME, s3_key, local_path)
                logger.info("Download completed.")
            except Exception as e:
                logger.error(f"Failed to download {s3_key}: {e}")
                return None
        return local_path

    def _init_session(self):
        """初始化 ONNX Session"""
        logger.info("Initializing Structure Segmentation Session...")
        model_path = self._download_if_needed(self.onnx_key)

        if model_path:
            try:
                self.session = ort.InferenceSession(model_path, providers=self.providers)
                self.input_name = self.session.get_inputs()[0].name
                logger.info(f"✅ Structure Model loaded. Device: {ort.get_device()}")
            except Exception as e:
                logger.critical(f"Structure Model init failed: {e}")

    def predict(self, image) -> dict:
        """
        执行分割
        Returns:
            dict: {
                "original_mask": np.array (H, W) uint8 0/1,
                "contours": [cnt1, cnt2, ...],
                "vis_image": np.array (仅用于调试可视化的叠加图)
            }
        """
        if self.session is None:
            return {}

        try:
            h, w = image.shape[:2]

            # 1. Preprocess (Resize 512 -> Norm -> Tensor -> Numpy)
            input_tensor = self.processor.preprocess_segmentation(image)
            input_numpy = input_tensor.cpu().numpy()

            # 2. Inference
            output = self.session.run(None, {self.input_name: input_numpy})[0]

            # 3. Postprocess (Argmax -> Resize back to Original H,W)
            # 解析 512x512 的 mask
            pred_mask_512 = self.processor._parse_output_to_mask(output)

            # 还原回原图尺寸 (最近邻插值保持 0/1)
            final_mask = cv2.resize(pred_mask_512.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)

            # 4. 提取轮廓 (用于生成 Polygon 接口数据)
            # 只提取外轮廓
            contours, _ = cv2.findContours(final_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            return {
                "mask": final_mask,  # 0/1 掩码
                "contours": contours  # 轮廓点
            }

        except Exception as e:
            logger.error(f"Structure Prediction Error: {e}")
            import traceback
            traceback.print_exc()
            return {}

    def visualize(self, image, result_dict, save_path="debug_structure.jpg"):
        """
        可视化验证函数：将 Mask 叠加在原图上
        """
        if "mask" not in result_dict:
            print("No mask to visualize.")
            return

        mask = result_dict["mask"]
        contours = result_dict["contours"]

        # 复制原图
        vis = image.copy()

        # 1. 绘制半透明填充
        # 创建一个纯色图层 (比如绿色)
        color_mask = np.zeros_like(vis)
        color_mask[mask == 1] = [0, 255, 0]  # BGR: 绿色

        # 叠加
        alpha = 0.4
        vis = cv2.addWeighted(vis, 1, color_mask, alpha, 0)

        # 2. 绘制轮廓线 (更清晰)
        cv2.drawContours(vis, contours, -1, (0, 255, 255), 2)  # 黄色轮廓

        # 保存
        cv2.imwrite(save_path, vis)
        print(f"✅ 可视化结果已保存: {save_path}")


# --- 单元测试 ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 1. 实例化
    predictor = SinusStructurePredictor()

    # 2. 构造测试图 (这里你可以换成读取本地真实图片的逻辑)
    # 比如: img = cv2.imread("test.jpg")
    img = np.random.randint(0, 255, (1000, 2000, 3), dtype=np.uint8)

    # 3. 预测
    print("Running prediction...")
    res = predictor.predict(img)

    # 4. 验证可视化
    print("Generating visualization...")
    predictor.visualize(img, res, "test_structure_mask.jpg")