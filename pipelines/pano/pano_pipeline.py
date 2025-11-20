# -*- coding: utf-8 -*-
"""
全景片推理管道
负责协调各个模块完成全景片的完整分析流程
"""

from pipelines.base_pipeline import BasePipeline
from pipelines.pano.utils import pano_report_utils
import logging

# 导入三个模块的预测器
from pipelines.pano.modules.candyle_seg import JointPredictor as CondyleSegPredictor
from pipelines.pano.modules.condyle_detection import JointPredictor as CondyleDetPredictor
from pipelines.pano.modules.mandible_seg import MandiblePredictor

logger = logging.getLogger(__name__)


class PanoPipeline(BasePipeline):
    """
    全景片推理管道
    
    负责协调各个子模块完成全景片的完整分析流程，并生成符合规范的 JSON 输出。
    子模块包括：牙齿分割、骨密度分析、关节检测等。
    
    架构设计（v3.2）：
        - 在初始化时，一次性加载所有 enabled 的模块
        - 支持多模块并存（teeth_seg, bone_density, joint 等）
        - 通过 modules 参数接收配置
    """
    
    def __init__(self, *, modules: dict = None):
        """
        初始化全景片 Pipeline
        
        Args:
            modules: 模块配置字典（可选）
                格式与 CephPipeline 相同，当前为空字典（子模块未实现）
        
        Note:
            - v3: 初始化基础结构，子模块用 TODO 占位
            - v4: 实现子模块的真实初始化
        """
        super().__init__()
        self.pipeline_type = "panoramic"
        self.modules = {}  # 存储所有已初始化的模块实例
        
        # 初始化三个核心模块
        logger.info("Initializing Pano Pipeline modules...")
        try:
            # 1. 髁突分割模块 (candyle_seg)
            self.modules['condyle_seg'] = CondyleSegPredictor()
            logger.info("  ✓ Condyle Segmentation module loaded")
            
            # 2. 髁突检测模块 (condyle_detection)
            self.modules['condyle_det'] = CondyleDetPredictor()
            logger.info("  ✓ Condyle Detection module loaded")
            
            # 3. 下颌骨分割模块 (mandible_seg)
            self.modules['mandible'] = MandiblePredictor()
            logger.info("  ✓ Mandible Segmentation module loaded")
            
        except Exception as e:
            logger.error(f"Failed to initialize some modules: {e}")
            raise
        
        logger.info("PanoPipeline initialized successfully")
    
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
            
        except Exception as e:
            logger.error(f"Inference failed: {e}")
            raise
        
        # 3. 收集所有结果
        logger.info("Collecting results from all modules...")
        
        # 调试日志：详细检查各模块的结果
        logger.debug(f"[Pipeline] condyle_seg_results keys: {list(condyle_seg_results.keys()) if condyle_seg_results else 'EMPTY'}")
        logger.debug(f"[Pipeline] condyle_det_results keys: {list(condyle_det_results.keys()) if condyle_det_results else 'EMPTY'}")
        logger.debug(f"[Pipeline] mandible_results keys: {list(mandible_results.keys()) if mandible_results else 'EMPTY'}")
        
        # 如果检测模块有结果，打印详细信息
        if condyle_det_results:
            logger.debug(f"[Pipeline] condyle_det left confidence: {condyle_det_results.get('left', {}).get('confidence', 'N/A')}")
            logger.debug(f"[Pipeline] condyle_det right confidence: {condyle_det_results.get('right', {}).get('confidence', 'N/A')}")
        
        inference_results = self._collect_results(
            condyle_seg=condyle_seg_results,
            condyle_det=condyle_det_results,
            mandible=mandible_results
        )
        logger.info(f"Results collected: condyle_seg={bool(condyle_seg_results)}, condyle_det={bool(condyle_det_results)}, mandible={bool(mandible_results)}")
        
        # 4. 生成符合规范的 JSON
        logger.info("Generating standard output...")
        # 准备 metadata
        metadata = {
            "ImageName": image_path.split("/")[-1] if "/" in image_path else image_path.split("\\")[-1],
            "DiagnosisID": "",  # TODO: 从外部传入
            "AnalysisTime": ""  # 由 pano_report_utils 自动生成
        }
        
        data_dict = pano_report_utils.generate_standard_output(metadata, inference_results)
        
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
    
    def _collect_results(self, **module_results) -> dict:
        """
        收集所有子模块的推理结果
        
        Args:
            **module_results: 各子模块结果
                - condyle_seg: 髁突分割结果
                - condyle_det: 髁突检测结果
                - mandible: 下颌骨分割结果
            
        Returns:
            dict: 汇总的推理结果
            
        Example:
            inference_results = {
                "condyle_seg": {...},
                "condyle_det": {...},
                "mandible": {...}
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
        }
        
        return inference_results
