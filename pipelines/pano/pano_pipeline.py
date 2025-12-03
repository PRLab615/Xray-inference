# -*- coding: utf-8 -*-
"""
全景片推理管道
负责协调各个模块完成全景片的完整分析流程
"""

from pipelines.base_pipeline import BasePipeline
from pipelines.pano.utils import pano_report_utils
from tools.timer import timer
import logging
import cv2
import numpy as np

# 导入预测器
from pipelines.pano.modules.condyle_seg import JointPredictor as CondyleSegPredictor
from pipelines.pano.modules.condyle_detection import JointPredictor as CondyleDetPredictor
from pipelines.pano.modules.mandible_seg import MandiblePredictor
from pipelines.pano.modules.implant_detect import ImplantDetectionModule
from pipelines.pano.modules.teeth_seg import TeethSegmentationModule, process_teeth_results
from pipelines.pano.modules.rootTipDensity_detect import RootTipDensityPredictor
from pipelines.pano.modules.sinus_seg.sinus_seg_predictor import SinusSegPredictor
from pipelines.pano.modules.sinus_class.sinus_class_predictor import SinusClassPredictor

logger = logging.getLogger(__name__)


class PanoPipeline(BasePipeline):
    """
    全景片推理管道
    
    负责协调各个子模块完成全景片的完整分析流程，并生成符合规范的 JSON 输出。
    架构设计（v3.5）：
        - 支持多模块并存（teeth, mandible, condyle, implant, sinus）
        - 上颌窦分析流程：分割(sinus_seg) -> 裁剪ROI -> 分类(sinus_class)
        - 所有模块配置通过 config 传入，避免硬编码
    """
    
    def __init__(self, *, modules: dict = None):
        """
        初始化全景片 Pipeline
        
        Args:
            modules: 模块配置字典，格式如下：
                {
                    "teeth_seg": {
                        "weights_key": "weights/panoramic/1116_teeth_seg.pt",
                        "device": "0",
                        ...
                    },
                    "mandible_seg": {...},
                    "implant_detect": {...},
                    "condyle_seg": {...},
                    "condyle_det": {...}
                }
        """
        super().__init__()
        self.pipeline_type = "panoramic"
        self.modules = {}  # 存储所有已初始化的模块实例
        self._modules_config = modules or {}
        
        # 初始化所有模块
        logger.info("Initializing Pano Pipeline modules...")
        self._initialize_modules()
        logger.info("PanoPipeline initialized successfully")
    
    def _get_module_config(self, module_name: str) -> dict:
        """
        获取指定模块的配置，排除元数据字段
        
        Args:
            module_name: 模块名称
            
        Returns:
            dict: 模块初始化参数
        """
        config = self._modules_config.get(module_name, {})
        if not isinstance(config, dict):
            return {}
        # 排除元数据字段
        exclude_keys = {'description'}
        return {k: v for k, v in config.items() if k not in exclude_keys}
    
    def _initialize_modules(self):
        """初始化所有模块，从配置中读取参数"""
        try:
            # 1. 髁突分割模块 (condyle_seg)
            condyle_seg_cfg = self._get_module_config('condyle_seg')
            self.modules['condyle_seg'] = CondyleSegPredictor(**condyle_seg_cfg)
            logger.info("  ✓ Condyle Segmentation module loaded")
            
            # 2. 髁突检测模块 (condyle_detection)
            condyle_det_cfg = self._get_module_config('condyle_det')
            self.modules['condyle_det'] = CondyleDetPredictor(**condyle_det_cfg)
            logger.info("  ✓ Condyle Detection module loaded")
            
            # 3. 下颌骨分割模块 (mandible_seg)
            mandible_cfg = self._get_module_config('mandible_seg')
            self.modules['mandible'] = MandiblePredictor(**mandible_cfg)
            logger.info("  ✓ Mandible Segmentation module loaded")
            
            # 4. 种植体检测模块 (implant_detect)
            implant_cfg = self._get_module_config('implant_detect')
            self.modules['implant_detect'] = ImplantDetectionModule(**implant_cfg)
            logger.info("  ✓ Implant Detection module loaded")
            
            # 5. 牙齿分割模块 (teeth_seg)
            teeth_cfg = self._get_module_config('teeth_seg')
            self.modules['teeth_seg'] = TeethSegmentationModule(**teeth_cfg)
            logger.info("  ✓ Teeth Segmentation module loaded")
            
            # 6. 上颌窦分割模块 (sinus_seg)
            sinus_seg_cfg = self._get_module_config('sinus_seg')
            self.modules['sinus_seg'] = SinusSegPredictor(**sinus_seg_cfg)
            logger.info("  ✓ Sinus Segmentation module loaded")
            
            # 7. 上颌窦分类模块 (sinus_class)
            sinus_class_cfg = self._get_module_config('sinus_class')
            self.modules['sinus_class'] = SinusClassPredictor(**sinus_class_cfg)
            logger.info("  ✓ Sinus Classification module loaded")
            
            # 8. 根尖低密度影检测模块 (rootTipDensity_detect)
            rootTipDensity_cfg = self._get_module_config('rootTipDensity_detect')
            self.modules['rootTipDensity_detect'] = RootTipDensityPredictor(**rootTipDensity_cfg)
            logger.info("  ✓ RootTipDensity Detection module loaded")
            
        except Exception as e:
            logger.error(f"Failed to initialize some modules: {e}")
            raise
    
    def run(self, image_path: str) -> dict:
        """
        执行全景片推理流程
        
        Args:
            image_path: 图像文件路径
            
        Returns:
            dict: 完整的 data 字段，符合《规范：全景片 JSON》
            
        Raises:
            FileNotFoundError: 图像文件不存在
            ValueError: 图像验证失败
            
        工作流程:
            1. 验证图像文件存在
            2. 依次调用各个子模块
            3. 收集所有推理结果
            4. 调用 report_utils 生成规范 JSON
            5. 返回完整的 data 字段
            
        Note:
            - 各子模块内部负责图像加载
            - 与 CephPipeline 保持一致的设计模式
        """
        # 重置计时器
        timer.reset()
        
        self._log_step("开始全景片推理", f"image_path={image_path}")
        
        # 1. 验证图像文件存在
        self._load_image(image_path)
        
        # 2. 依次调用各个子模块（直接传递 image_path）
        try:
            # 2.1 髁突分割
            condyle_seg_results = self._run_condyle_seg(image_path)
            
            # 2.2 髁突检测
            condyle_det_results = self._run_condyle_detection(image_path)
            
            # 2.3 下颌骨分割
            mandible_results = self._run_mandible_seg(image_path)
            
            # 2.4 种植体检测
            implant_results = self._run_implant_detect(image_path)
            
            # 2.5 牙齿分割
            teeth_results = self._run_teeth_seg(image_path)
            
            # 2.6 上颌窦分析 (分割 + 分类)
            sinus_results = self._run_sinus_workflow(image_path)
            
            # 2.7 根尖低密度影检测
            rootTipDensity_results = self._run_rootTipDensity_detect(image_path)
            
        except Exception as e:
            logger.error(f"Inference failed: {e}")
            raise
        
        # 3. 收集所有结果
        logger.info("Collecting results from all modules...")
        
        # 调试日志：详细检查各模块的结果
        logger.debug(f"[Pipeline] condyle_seg_results keys: {list(condyle_seg_results.keys()) if condyle_seg_results else 'EMPTY'}")
        logger.debug(f"[Pipeline] condyle_det_results keys: {list(condyle_det_results.keys()) if condyle_det_results else 'EMPTY'}")
        logger.debug(f"[Pipeline] mandible_results keys: {list(mandible_results.keys()) if mandible_results else 'EMPTY'}")
        logger.debug(f"[Pipeline] implant_results keys: {list(implant_results.keys()) if implant_results else 'EMPTY'}")
        logger.debug(f"[Pipeline] teeth_results keys: {list(teeth_results.keys()) if teeth_results else 'EMPTY'}")
        logger.debug(f"[Pipeline] sinus_results keys: {list(sinus_results.keys()) if sinus_results else 'EMPTY'}")
        
        # 如果检测模块有结果，打印详细信息
        if condyle_det_results:
            logger.debug(f"[Pipeline] condyle_det left confidence: {condyle_det_results.get('left', {}).get('confidence', 'N/A')}")
            logger.debug(f"[Pipeline] condyle_det right confidence: {condyle_det_results.get('right', {}).get('confidence', 'N/A')}")
        
        inference_results = self._collect_results(
            condyle_seg=condyle_seg_results,
            condyle_det=condyle_det_results,
            mandible=mandible_results,
            implant=implant_results,
            teeth=teeth_results,
            sinus=sinus_results,  # 加入上颌窦结果
            rootTipDensity=rootTipDensity_results  # 加入根尖低密度影结果
        )
        logger.info(f"Results collected successfully. Modules: {list(inference_results.keys())}")
        
        # 4. 生成符合规范的 JSON
        logger.info("Generating standard output...")
        # 准备 metadata
        metadata = {
            "ImageName": image_path.split("/")[-1] if "/" in image_path else image_path.split("\\")[-1],
            "DiagnosisID": "",  # TODO: 从外部传入
            "AnalysisTime": ""  # 由 pano_report_utils 自动生成
        }
        
        # 报告生成
        with timer.record("report.generation"):
            data_dict = pano_report_utils.generate_standard_output(metadata, inference_results)
        
        # 保存计时报告
        timer.print_report()
        timer.save_report()
        
        self._log_step("全景片推理完成", f"data keys: {list(data_dict.keys())}")
        logger.info("Pano pipeline run completed successfully")
        
        return data_dict
    
    def _run_condyle_seg(self, image_path: str) -> dict:
        """
        执行髁突分割
        
        Args:
            image_path: 图像文件路径
            
        Returns:
            dict: 髁突分割结果
                包含 raw_features 和 analysis
        """
        self._log_step("髁突分割", "使用 ONNX 模型进行分割")
        
        try:
            import time
            import cv2
            start_time = time.time()
            logger.info(f"Starting condyle segmentation for: {image_path}")
            
            # 加载图像
            image = cv2.imread(image_path)
            if image is None:
                raise ValueError(f"Failed to load image: {image_path}")
            
            results = self.modules['condyle_seg'].predict(image)
            
            elapsed = time.time() - start_time
            logger.info(f"Condyle segmentation completed in {elapsed:.2f}s")
            return results
        except Exception as e:
            logger.error(f"Condyle segmentation failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}
    
    def _run_condyle_detection(self, image_path: str) -> dict:
        """
        执行髁突检测
        
        Args:
            image_path: 图像文件路径
            
        Returns:
            dict: 髁突检测结果
                包含 left 和 right 的检测框和分类
        """
        self._log_step("髁突检测", "使用 YOLOv11 进行检测")
        
        try:
            import time
            start_time = time.time()
            logger.info(f"Starting condyle detection for: {image_path}")
            
            # 传递图像路径给 YOLO predictor
            results = self.modules['condyle_det'].predict(image_path)
            
            elapsed = time.time() - start_time
            logger.info(f"Condyle detection completed in {elapsed:.2f}s")
            return results
        except Exception as e:
            logger.error(f"Condyle detection failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}
    
    def _run_mandible_seg(self, image_path: str) -> dict:
        """
        执行下颌骨分割
        
        Args:
            image_path: 图像文件路径
            
        Returns:
            dict: 下颌骨分割结果
                包含 analysis 和几何测量数据
        """
        self._log_step("下颌骨分割", "使用 TransUNet 进行分割")
        
        try:
            import time
            import cv2
            start_time = time.time()
            logger.info(f"Starting mandible segmentation for: {image_path}")
            
            # 加载图像
            image = cv2.imread(image_path)
            if image is None:
                raise ValueError(f"Failed to load image: {image_path}")
            
            results = self.modules['mandible'].predict(image)
            
            elapsed = time.time() - start_time
            logger.info(f"Mandible segmentation completed in {elapsed:.2f}s")
            return results
        except Exception as e:
            logger.error(f"Mandible segmentation failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}
    
    def _run_implant_detect(self, image_path: str) -> dict:
        """
        执行种植体检测
        
        Args:
            image_path: 图像文件路径
            
        Returns:
            dict: 种植体检测结果
                包含 implant_boxes 和 quadrant_counts
        """
        self._log_step("种植体检测", "使用 YOLOv11 进行种植体检测")
        
        try:
            import time
            from PIL import Image
            start_time = time.time()
            logger.info(f"Starting implant detection for: {image_path}")
            
            # 加载图像为 PIL Image
            image = Image.open(image_path).convert('RGB')
            if image is None:
                raise ValueError(f"Failed to load image: {image_path}")
            
            results = self.modules['implant_detect'].predict(image)
            
            elapsed = time.time() - start_time
            logger.info(f"Implant detection completed in {elapsed:.2f}s")
            return results
        except Exception as e:
            logger.error(f"Implant detection failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}
    
    def _run_teeth_seg(self, image_path: str) -> dict:
        """
        执行牙齿分割
        
        Args:
            image_path: 图像文件路径
            
        Returns:
            dict: 牙齿分割结果（经过后处理）
                包含缺牙、智齿、乳牙等分析结果
        """
        self._log_step("牙齿分割", "使用 YOLOv11 进行牙齿实例分割")
        
        try:
            import time
            from PIL import Image
            start_time = time.time()
            logger.info(f"Starting teeth segmentation for: {image_path}")
            
            # 加载图像为 PIL Image
            image = Image.open(image_path).convert('RGB')
            if image is None:
                raise ValueError(f"Failed to load image: {image_path}")
            
            # 执行推理（内部已埋点 teeth_seg.inference 和 teeth_seg.post）
            raw_results = self.modules['teeth_seg'].predict(image)
            
            # 后处理：生成缺牙、智齿、乳牙等报告（业务逻辑处理，不计时）
            processed_results = process_teeth_results(raw_results)
            
            elapsed = time.time() - start_time
            logger.info(f"Teeth segmentation completed in {elapsed:.2f}s")
            return processed_results
        except Exception as e:
            logger.error(f"Teeth segmentation failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}
    
    def _run_sinus_workflow(self, image_path: str) -> dict:
        """
        执行上颌窦分析工作流：
        1. 分割 (Sinus Seg): 获取 mask
        2. 逻辑处理: 连通域分析、左右侧判定、ROI 裁剪
        3. 分类 (Sinus Class): 对 ROI 进行炎症判断
        
        Args:
            image_path: 图像路径
            
        Returns:
            dict: 包含结果列表和 mask 信息
        """
        self._log_step("上颌窦分析", "分割(sinus_seg) + 分类(sinus_class)")
        
        try:
            import time
            start_time = time.time()
            
            # 1. 准备图片
            image = cv2.imread(image_path)
            if image is None:
                raise ValueError(f"Failed to load image: {image_path}")
            h, w = image.shape[:2]
            
            # 2. 分割 (Sinus Seg)
            # 调用分割模块，获取全图 Mask
            # 注意：predict 方法内部已经分别计时 pre/inference/post
            logger.info("Running Sinus Segmentation...")
            seg_res = self.modules['sinus_seg'].predict(image)
            mask_full = seg_res.get('mask')  # 预期 Seg 模块返回 {'mask': np.array}
            
            if mask_full is None:
                logger.warning("Sinus segmentation returned no mask.")
                return {}
            
            # 3. 连通域分析 (获取左右侧 ROI)
            num, labels, stats, _ = cv2.connectedComponentsWithStats(mask_full, connectivity=8)
            
            logger.info(f"Found {num - 1} sinus components.")
            
            # 按侧别分组连通域，每侧只保留面积最大的连通域
            side_components = {'left': [], 'right': []}
            
            for i in range(1, num):
                # 过滤小面积噪点
                area = stats[i, cv2.CC_STAT_AREA]
                if area < 500: 
                    continue
                
                # 获取边界框
                x, y, sw, sh = stats[i][:4]
                # 判定左右侧：直接用边界框 x 坐标判断（左右窦不会重叠）
                # 图像左侧 = 患者右侧
                location = "Right" if x < (w / 2) else "Left"
                side_lower = location.lower()
                
                side_components[side_lower].append({
                    'index': i,
                    'area': area,
                    'bbox': (x, y, sw, sh),
                    'location': location
                })
            
            results_list = []
            masks_info = []
            
            # 对每一侧只处理面积最大的连通域
            for side_lower in ['right', 'left']:
                components = side_components[side_lower]
                if not components:
                    continue
                
                # 选择面积最大的连通域
                largest = max(components, key=lambda c: c['area'])
                x, y, sw, sh = largest['bbox']
                location = largest['location']
                component_index = largest['index']
                
                logger.info(f"Processing {location} sinus (largest of {len(components)} components, area={largest['area']})")
                
                # 提取该连通域的 mask（用于前端可视化）
                side_mask = (labels == component_index).astype(np.uint8)
                
                # 提取轮廓坐标
                contour_coords = []
                try:
                    contours, _ = cv2.findContours(
                        side_mask,
                        cv2.RETR_EXTERNAL,
                        cv2.CHAIN_APPROX_SIMPLE
                    )
                    if contours:
                        # 取最大轮廓
                        largest_contour = max(contours, key=cv2.contourArea)
                        coords = largest_contour.squeeze()
                        if coords.ndim == 1:
                            contour_coords = [coords.tolist()]
                        else:
                            contour_coords = coords.tolist()
                        logger.info(f"Extracted {len(contour_coords)} contour points for {location} sinus")
                except Exception as e:
                    logger.warning(f"Failed to extract contour for {location} sinus: {e}")
                
                # 裁剪 ROI (加 Padding)
                pad = 30
                x1, y1 = max(0, x - pad), max(0, y - pad)
                x2, y2 = min(w, x + sw + pad), min(h, y + sh + pad)
                
                crop = image[y1:y2, x1:x2]
                
                # 4. 分类 (Sinus Class)
                is_inflam = False
                conf = 0.0
                
                if crop.size > 0:
                    logger.info(f"Classifying {location} sinus ROI...")
                    # 调用分类模块，传入 Crop 图片
                    # 注意：predict 方法内部已经分别计时 pre/inference/post
                    cls_res = self.modules['sinus_class'].predict(crop)
                    is_inflam = cls_res.get('is_inflam', False)
                    conf = cls_res.get('confidence', 0.0)
                else:
                    logger.warning(f"Invalid crop for {location} sinus.")
                
                # 5. 构造结果
                cn_side = "左" if side_lower == 'left' else "右"
                detail = f"{cn_side}上颌窦" + ("可见炎症影像，建议复查。" if is_inflam else "气化良好。")
                
                results_list.append({
                    "Side": side_lower,
                    "Pneumatization": 0,  # 暂时不开启气化判断
                    "TypeClassification": 0,
                    "Inflammation": is_inflam,
                    "RootEntryToothFDI": [],
                    "Detail": detail,
                    "Confidence_Pneumatization": 0.99,
                    "Confidence_Inflammation": float(f"{conf:.2f}")
                })
                
                # 包含 mask 和 contour 用于前端可视化
                masks_info.append({
                    "label": f"sinus_{side_lower}",
                    "bbox": [int(x), int(y), int(sw), int(sh)],
                    "mask": side_mask,  # numpy array，会在 report_utils 中转为 RLE
                    "contour": contour_coords  # [[x, y], [x, y], ...] 格式
                })
            
            elapsed = time.time() - start_time
            logger.info(f"Sinus workflow completed in {elapsed:.2f}s")
            
            return {"MaxillarySinus": results_list, "masks_info": masks_info}
            
        except Exception as e:
            logger.error(f"Sinus workflow failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}
    
    def _run_rootTipDensity_detect(self, image_path: str) -> dict:
        """
        执行根尖低密度影检测
        
        Args:
            image_path: 图像文件路径
            
        Returns:
            dict: 根尖低密度影检测结果
                包含 density_boxes 和 quadrant_counts
        """
        self._log_step("根尖低密度影检测", "使用 YOLOv11 进行检测")
        
        try:
            import time
            from PIL import Image
            start_time = time.time()
            logger.info(f"Starting rootTipDensity detection for: {image_path}")
            
            # 加载图像为 PIL Image
            image = Image.open(image_path).convert('RGB')
            if image is None:
                raise ValueError(f"Failed to load image: {image_path}")
            
            results = self.modules['rootTipDensity_detect'].predict(image)
            
            elapsed = time.time() - start_time
            logger.info(f"RootTipDensity detection completed in {elapsed:.2f}s")
            return results
        except Exception as e:
            logger.error(f"RootTipDensity detection failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}
    
    def _collect_results(self, **module_results) -> dict:
        """
        收集所有子模块的推理结果
        
        Args:
            **module_results: 各子模块结果
                - condyle_seg: 髁突分割结果
                - condyle_det: 髁突检测结果
                - mandible: 下颌骨分割结果
                - implant: 种植体检测结果
                - teeth: 牙齿分割结果
                - sinus: 上颌窦分析结果
            
        Returns:
            dict: 汇总的推理结果
            
        Example:
            inference_results = {
                "condyle_seg": {...},
                "condyle_det": {...},
                "mandible": {...},
                "implant": {...},
                "teeth": {...},
                "sinus": {...}
            }
            
        Note:
            - 将各子模块的结果汇总到统一的字典中
            - 为后续的 report_utils 格式化做准备
        """
        self._log_step("收集结果", f"{len(module_results)} modules")
        
        inference_results = {
            "condyle_seg": module_results.get("condyle_seg", {}),
            "condyle_det": module_results.get("condyle_det", {}),
            "mandible": module_results.get("mandible", {}),
            "implant": module_results.get("implant", {}),
            "teeth": module_results.get("teeth", {}),
            "sinus": module_results.get("sinus", {}),  # 收集上颌窦结果
            "rootTipDensity": module_results.get("rootTipDensity", {}),  # 收集根尖低密度影结果
        }
        
        return inference_results
