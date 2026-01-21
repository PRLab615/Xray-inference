# -*- coding: utf-8 -*-
import logging
from typing import Dict, List, Optional, Any, Union
import numpy as np
from ultralytics import YOLO
from tools.weight_fetcher import ensure_weight_file

class AutoRulerModel:
    """
    自动比例尺识别模型封装 (YOLOv11)
    """
    def __init__(
        self, 
        weights_key: str, 
        device: str = "0", 
        conf: float = 0.25, 
        iou: float = 0.45, 
        image_size: int = 1024,
        **kwargs
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.device = device
        self.conf = conf
        self.iou = iou
        self.image_size = image_size
        
        # 加载权重
        weight_path = ensure_weight_file(weights_key, force_download=kwargs.get('weights_force_download', False))
        self.model = YOLO(weight_path)
        self.logger.info(f"AutoRuler model loaded from {weight_path}")

    def predict(self, image: Union[str, np.ndarray]) -> Optional[Dict[str, Any]]:
        """
        执行推理并返回比例尺的两个端点
        
        Args:
            image: 图像路径或numpy数组
            
        Returns:
            dict: {
                "points": [[x1, y1], [x2, y2]],
                "distance_mm": 10
            }
            or None if no ruler detected
        """
        try:
            results = self.model.predict(
                source=image,
                device=self.device,
                conf=self.conf,
                iou=self.iou,
                imgsz=self.image_size,
                verbose=False
            )
            
            if not results:
                return None
                
            result = results[0]
            
            # 假设模型输出的是关键点 (Pose模型)
            if result.keypoints is not None and result.keypoints.has_visible:
                # 取第一个检测到的对象的关键点
                # 假设只有两个关键点：端点1和端点2
                kpts = result.keypoints.xy.cpu().numpy()[0] # shape (N, 2)
                
                if len(kpts) >= 2:
                    p1 = kpts[0].tolist()
                    p2 = kpts[1].tolist()
                    
                    # 简单的有效性检查：如果点是(0,0)，可能无效
                    if (p1[0] == 0 and p1[1] == 0) or (p2[0] == 0 and p2[1] == 0):
                        self.logger.warning("Detected ruler points contain (0,0), ignoring")
                        return None
                        
                    return {
                        "points": [p1, p2],
                        "distance_mm": 10
                    }
            
            # 如果是检测框 (Detect模型)，可能检测到两个点作为两个对象
            elif result.boxes is not None and len(result.boxes) >= 2:
                # 取置信度最高的两个框的中心点
                boxes = result.boxes.xywh.cpu().numpy() # x_center, y_center, w, h
                # 按置信度排序? 这里假设前两个就是
                p1 = boxes[0][:2].tolist()
                p2 = boxes[1][:2].tolist()
                
                return {
                    "points": [p1, p2],
                    "distance_mm": 10
                }
                
            return None
            
        except Exception as e:
            self.logger.error(f"Error during auto ruler prediction: {e}")
            return None
