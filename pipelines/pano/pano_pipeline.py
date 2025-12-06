# -*- coding: utf-8 -*-
"""
全景片推理管道
负责协调各个模块完成全景片的完整分析流程
"""

from pipelines.base_pipeline import BasePipeline
from pipelines.pano.utils import pano_report_utils
from tools.timer import timer
import logging
from datetime import datetime
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
# 导入牙齿属性检测模块
from pipelines.pano.modules.teeth_attribute1.teeth_attribute1_predictor import TeethAttributeModule
from pipelines.pano.modules.teeth_attribute2.teeth_attribute2_predictor import TeethAttribute2Module
from pipelines.pano.modules.curved_short_root.curved_short_root_predictor import CurvedShortRootModule
from pipelines.pano.modules.erupted_wisdomteeth.erupted_wisdomteeth_predictor import EruptedModule

logger = logging.getLogger(__name__)

# 与临时代码 code/config.py 保持一致的一些常量和规则，用于在 Pipeline 层完成分析
# 注意：这些常量后续 code 目录删除后，仍然以此处为“单一事实来源”

# 智齿 FDI
WISDOM_TEETH_FDI = ["18", "28", "38", "48"]

# 所有恒牙 FDI
ALL_PERMANENT_TEETH_FDI = [
    "11", "12", "13", "14", "15", "16", "17", "18",
    "21", "22", "23", "24", "25", "26", "27", "28",
    "31", "32", "33", "34", "35", "36", "37", "38",
    "41", "42", "43", "44", "45", "46", "47", "48",
]

# 属性到中文描述映射（复制自 code/config.py）
ATTRIBUTE_DESCRIPTION_MAP = {
    "area": "病灶区域",
    "carious_lesion": "龋坏",
    "curved_short_root": "牙根形态弯曲短小",
    "embedded_tooth": "埋伏牙",
    "erupted": "已萌出",
    "impacted": "阻生",
    "implant": "种植体病灶",
    "not_visible": "不可见",
    "periodontal": "牙周病灶",
    "rct_treated": "根管治疗",
    "residual_crown": "残冠",
    "residual_root": "残根",
    "restored_tooth": "修复牙",
    "retained_primary_tooth": "滞留乳牙",
    "root_absorption": "牙根吸收",
    "to_be_erupted": "待萌出",
    "tooth_germ": "牙胚",
    "wisdom_tooth_impaction": "智齿阻生",
}

# 与 code/config.py 一致的阈值设置
CONF_THRESHOLD = 0.3
IOU_THRESHOLD = 0.5


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
        from tools.weight_fetcher import WeightFetchError
        
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


            # 8. 牙齿属性检测模块1 (teeth_attribute1)
            teeth_attr1_cfg = self._get_module_config('teeth_attribute1')
            self.modules['teeth_attribute1'] = TeethAttributeModule(**teeth_attr1_cfg)
            logger.info("  ✓ Teeth Attribute1 module loaded")

            # 9. 牙齿属性检测模块2 (teeth_attribute2)
            teeth_attr2_cfg = self._get_module_config('teeth_attribute2')
            self.modules['teeth_attribute2'] = TeethAttribute2Module(**teeth_attr2_cfg)
            logger.info("  ✓ Teeth Attribute2 module loaded")

            # 10. 牙齿属性检测模块3-压根形态弯曲短小 (curved_short_root)
            teeth_attr3_cfg = self._get_module_config('curved_short_root')
            self.modules['curved_short_root'] = CurvedShortRootModule(**teeth_attr3_cfg)
            logger.info("  ✓ curved_short_root module loaded")

            # 11. 牙齿属性检测模块4-智齿已萌出 (erupted_wisdomteeth)
            teeth_attr4_cfg = self._get_module_config('erupted_wisdomteeth')
            self.modules['erupted_wisdomteeth'] = EruptedModule(**teeth_attr4_cfg)
            logger.info("  ✓ erupted_wisdomteeth module loaded")

            # 12. 根尖低密度影检测模块 (rootTipDensity_detect)
            rootTipDensity_cfg = self._get_module_config('rootTipDensity_detect')
            self.modules['rootTipDensity_detect'] = RootTipDensityPredictor(**rootTipDensity_cfg)
            logger.info("  ✓ RootTipDensity Detection module loaded")


        except (WeightFetchError, FileNotFoundError) as e:
            # 权重加载失败：本地缓存没有且S3连接失败
            logger.error(f"Failed to load model weights: {e}")
            logger.warning("Entering MOCK MODE: Will return example JSON data for all inference requests")
            self.is_mock_mode = True
        except Exception as e:
            # 其他初始化错误仍然抛出（不通过错误消息判断，避免误判）
            logger.error(f"Failed to initialize some modules: {e}")
            raise

    def run(
        self, 
        image_path: str,
        pixel_spacing: dict = None,
        **kwargs,
    ) -> dict:
        """
        执行全景片推理流程

        Args:
            image_path: 图像文件路径
            pixel_spacing: 像素间距/比例尺信息（可选）
                - scale_x: 水平方向 1像素 = 多少mm
                - scale_y: 垂直方向 1像素 = 多少mm
                - source: 数据来源（"dicom" 或 "request"）
            **kwargs: 其他参数（兼容性保留）

        Returns:
            dict: 完整的 data 字段，符合《规范：全景片 JSON》

        Raises:
            FileNotFoundError: 图像文件不存在
            ValueError: 图像验证失败

        工作流程:
            1. 验证图像文件存在
            2. 依次调用各个子模块
            3. 收集所有推理结果
            4. 调用 report_utils 生成规范 JSON（包含 ImageSpacing）
            5. 返回完整的 data 字段

        Note:
            - 各子模块内部负责图像加载
            - 与 CephPipeline 保持一致的设计模式
            - 如果处于mock模式，直接返回示例JSON
        """
        # Mock模式：返回示例JSON
        if self.is_mock_mode:
            from server.utils.mock_data_loader import load_example_json
            logger.warning("Pipeline is in MOCK MODE, returning example JSON data")
            example_data = load_example_json('panoramic')
            if example_data:
                # 示例JSON可能包含完整的响应结构，需要提取data字段
                if 'data' in example_data:
                    return example_data['data']
                return example_data
            else:
                logger.error("Failed to load example JSON, returning empty dict")
                return {}
        
        # 从 kwargs 获取 pixel_spacing（兼容旧调用方式）
        pixel_spacing = pixel_spacing or kwargs.get("pixel_spacing")
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

            # 2.6 牙齿属性检测1
            teeth_attribute1_results = self._run_teeth_attribute1(image_path)

            # 2.7 牙齿属性检测2
            teeth_attribute2_results = self._run_teeth_attribute2(image_path)

            # 2.8 牙齿属性检测3-压根形态弯曲短小
            curved_short_root_results = self._run_curved_short_root(image_path)

            # 2.9 牙齿属性检测4-智齿已萌出
            erupted_wisdomteeth_results = self._run_erupted_wisdomteeth(image_path)

            # 2.10 上颌窦分析 (分割 + 分类 + 气化判断)
            # 需要传入牙齿分割结果和比例尺，用于计算上颌窦气化类型
            sinus_results = self._run_sinus_workflow(
                image_path, 
                teeth_results=teeth_results,
                pixel_spacing=pixel_spacing
            )

            # 2.11 根尖低密度影检测
            rootTipDensity_results = self._run_rootTipDensity_detect(image_path)

        except Exception as e:
            logger.error(f"Inference failed: {e}")
            raise

        # 3. 在 Pipeline 内完成牙位-属性绑定、缺失牙和智齿分析
        logger.info("Analyzing teeth and attributes in pipeline...")
        try:
            teeth_analysis = self._analyze_teeth_and_attributes(
                teeth_results or {},
                teeth_attribute1_results or {},
                teeth_attribute2_results or {},
                curved_short_root_results or {},
                erupted_wisdomteeth_results or {},
            )
            # 将分析结果写回 teeth_results，供 report_utils 仅做格式转换
            if teeth_results is None:
                teeth_results = {}
            teeth_results["MissingTeeth"] = teeth_analysis.get("MissingTeeth", [])
            teeth_results["ThirdMolarSummary"] = teeth_analysis.get("ThirdMolarSummary", {})
            teeth_results["ToothAttributes"] = teeth_analysis.get("ToothAttributes", {})
        except Exception as exc:
            logger.error(f"Teeth + attributes analysis failed in pipeline: {exc}")

        # 4. 收集所有结果
        logger.info("Collecting results from all modules...")

        # 调试日志：详细检查各模块的结果
        logger.debug(f"[Pipeline] condyle_seg_results keys: {list(condyle_seg_results.keys()) if condyle_seg_results else 'EMPTY'}")
        logger.debug(f"[Pipeline] condyle_det_results keys: {list(condyle_det_results.keys()) if condyle_det_results else 'EMPTY'}")
        logger.debug(f"[Pipeline] mandible_results keys: {list(mandible_results.keys()) if mandible_results else 'EMPTY'}")
        logger.debug(f"[Pipeline] implant_results keys: {list(implant_results.keys()) if implant_results else 'EMPTY'}")
        logger.debug(f"[Pipeline] teeth_results keys: {list(teeth_results.keys()) if teeth_results else 'EMPTY'}")
        logger.debug(f"[Pipeline] teeth_attribute1_results keys: {list(teeth_attribute1_results.keys()) if teeth_attribute1_results else 'EMPTY'}")
        logger.debug(f"[Pipeline] teeth_attribute2_results keys: {list(teeth_attribute2_results.keys()) if teeth_attribute2_results else 'EMPTY'}")
        logger.debug(f"[Pipeline] curved_short_root_results keys: {list(curved_short_root_results.keys()) if curved_short_root_results else 'EMPTY'}")
        logger.debug(f"[Pipeline] erupted_wisdomteeth_results keys: {list(erupted_wisdomteeth_results.keys()) if erupted_wisdomteeth_results else 'EMPTY'}")
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
            teeth_attribute1=teeth_attribute1_results,
            teeth_attribute2=teeth_attribute2_results,
            curved_short_root=curved_short_root_results,
            erupted_wisdomteeth=erupted_wisdomteeth_results,
            rootTipDensity=rootTipDensity_results  # 加入根尖低密度影结果
        )
        logger.info(f"Results collected successfully. Modules: {list(inference_results.keys())}")
        
        # 4. 生成符合规范的 JSON
        logger.info("Generating standard output...")
        # 准备 metadata（对齐 code/analysis.py 中 format_to_json 的生成规则）
        image_name = image_path.split("/")[-1] if "/" in image_path else image_path.split("\\")[-1]
        metadata = {
            "ImageName": image_name,
            "DiagnosisID": f"AI-DX-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            "AnalysisTime": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        # 报告生成（传入 pixel_spacing 以生成 ImageSpacing 字段）
        with timer.record("report.generation"):
            data_dict = pano_report_utils.generate_standard_output(
                metadata, 
                inference_results,
                pixel_spacing=pixel_spacing
            )

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

            # 后处理：生成缺牙、智齿、乳牙等报告
            with timer.record("teeth_seg.analysis"):
                processed_results = process_teeth_results(raw_results)

            elapsed = time.time() - start_time
            logger.info(f"Teeth segmentation completed in {elapsed:.2f}s")
            return processed_results
        except Exception as e:
            logger.error(f"Teeth segmentation failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}

    def _run_teeth_attribute1(self, image_path: str) -> dict:
        """ 执行牙齿属性1检测
        Args:
            image_path: 图像文件路径
        Returns:
            dict: 牙齿属性1检测结果
        """
        self._log_step("牙齿属性检测1", "使用 YOLOv11 进行属性检测")
        try:
            import time
            from PIL import Image
            start_time = time.time()
            logger.info(f"Starting teeth attribute1 detection for: {image_path}")
            # 加载图像为 PIL Image
            image = Image.open(image_path).convert('RGB')
            if image is None:
                raise ValueError(f"Failed to load image: {image_path}")
            # 执行推理
            raw_results = self.modules['teeth_attribute1'].predict(image)
            elapsed = time.time() - start_time
            logger.info(f"Teeth attribute1 detection completed in {elapsed:.2f}s")
            return raw_results
        except Exception as e:
            logger.error(f"Teeth attribute1 detection failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}

    def _run_teeth_attribute2(self, image_path: str) -> dict:
        """ 执行牙齿属性2检测
        Args:
            image_path: 图像文件路径
        Returns:
            dict: 牙齿属性2检测结果
        """
        self._log_step("牙齿属性检测2", "使用 YOLOv11 进行属性检测")
        try:
            import time
            from PIL import Image
            start_time = time.time()
            logger.info(f"Starting teeth attribute2 detection for: {image_path}")
            # 加载图像为 PIL Image
            image = Image.open(image_path).convert('RGB')
            if image is None:
                raise ValueError(f"Failed to load image: {image_path}")
            # 执行推理
            raw_results = self.modules['teeth_attribute2'].predict(image)
            elapsed = time.time() - start_time
            logger.info(f"Teeth attribute2 detection completed in {elapsed:.2f}s")
            return raw_results
        except Exception as e:
            logger.error(f"Teeth attribute2 detection failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}

    def _run_curved_short_root(self, image_path: str) -> dict:
        """ 执行牙根形态弯曲短小检测
        Args:
            image_path: 图像文件路径
        Returns:
            dict: 牙根形态弯曲短小检测结果
        """
        self._log_step("牙根形态弯曲短小检测", "使用 YOLOv11 进行属性检测")
        try:
            import time
            from PIL import Image
            start_time = time.time()
            logger.info(f"Starting curved short root detection for: {image_path}")
            # 加载图像为 PIL Image
            image = Image.open(image_path).convert('RGB')
            if image is None:
                raise ValueError(f"Failed to load image: {image_path}")
            # 执行推理
            raw_results = self.modules['curved_short_root'].predict(image)
            elapsed = time.time() - start_time
            logger.info(f"Curved short root detection completed in {elapsed:.2f}s")
            return raw_results
        except Exception as e:
            logger.error(f"Curved short root detection failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}

    def _run_erupted_wisdomteeth(self, image_path: str) -> dict:
        """ 执行智齿已萌出检测
        Args:
            image_path: 图像文件路径
        Returns:
            dict: 智齿已萌出检测结果
        """
        self._log_step("智齿已萌出检测", "使用 YOLOv11 进行属性检测")
        try:
            import time
            from PIL import Image
            start_time = time.time()
            logger.info(f"Starting erupted wisdomteeth detection for: {image_path}")
            # 加载图像为 PIL Image
            image = Image.open(image_path).convert('RGB')
            if image is None:
                raise ValueError(f"Failed to load image: {image_path}")
            # 执行推理
            raw_results = self.modules['erupted_wisdomteeth'].predict(image)
            elapsed = time.time() - start_time
            logger.info(f"Erupted wisdomteeth detection completed in {elapsed:.2f}s")
            return raw_results
        except Exception as e:
            logger.error(f"Erupted wisdomteeth detection failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}

    def _run_sinus_workflow(
        self, 
        image_path: str, 
        teeth_results: dict = None,
        pixel_spacing: dict = None
    ) -> dict:
        """
        执行上颌窦分析工作流：
        1. 分割 (Sinus Seg): 获取 mask
        2. 逻辑处理: 连通域分析、左右侧判定、ROI 裁剪
        3. 分类 (Sinus Class): 对 ROI 进行炎症判断
        4. 气化判断: 计算上颌窦底与上颌后牙根尖距离

        上颌窦气化类型标准:
            - Ⅰ型: 正常气化或未气化，上颌窦底与上颌后牙根尖距离 > 3mm
            - Ⅱ型: 显著气化，上颌窦底与上颌后牙根尖距离在 0~3mm 范围内
            - Ⅲ型: 过度气化，上颌窦底与上颌后牙根尖距离 < 0mm（牙根进入上颌窦）

        Args:
            image_path: 图像路径
            teeth_results: 牙齿分割结果（用于气化判断）
            pixel_spacing: 像素间距/比例尺（用于距离计算）
                - scale_x: 水平方向 1像素 = 多少mm
                - scale_y: 垂直方向 1像素 = 多少mm

        Returns:
            dict: 包含结果列表和 mask 信息
        """
        self._log_step("上颌窦分析", "分割(sinus_seg) + 分类(sinus_class) + 气化判断")

        # 上颌后牙 FDI 定义（用于气化判断）
        # 右侧上颌后牙：14-18（图像左侧 = 患者右侧）
        # 左侧上颌后牙：24-28（图像右侧 = 患者左侧）
        UPPER_POSTERIOR_TEETH = {
            "right": ["14", "15", "16", "17", "18"],  # 患者右侧
            "left": ["24", "25", "26", "27", "28"]    # 患者左侧
        }

        try:
            import time
            start_time = time.time()

            # 1. 准备图片
            image = cv2.imread(image_path)
            if image is None:
                raise ValueError(f"Failed to load image: {image_path}")
            h, w = image.shape[:2]

            # 2. 分割 (Sinus Seg)
            logger.info("Running Sinus Segmentation...")
            seg_res = self.modules['sinus_seg'].predict(image)
            mask_full = seg_res.get('mask')

            if mask_full is None:
                logger.warning("Sinus segmentation returned no mask.")
                return {}

            # 3. 连通域分析 (获取左右侧 ROI)
            num, labels, stats, _ = cv2.connectedComponentsWithStats(mask_full, connectivity=8)
            logger.info(f"Found {num - 1} sinus components.")

            # 按侧别分组连通域，每侧只保留面积最大的连通域
            side_components = {'left': [], 'right': []}

            for i in range(1, num):
                area = stats[i, cv2.CC_STAT_AREA]
                if area < 500:
                    continue

                x, y, sw, sh = stats[i][:4]
                # 图像左侧 = 患者右侧
                location = "Right" if x < (w / 2) else "Left"
                side_lower = location.lower()

                side_components[side_lower].append({
                    'index': i,
                    'area': area,
                    'bbox': (x, y, sw, sh),
                    'location': location
                })

            # 4. 准备牙齿根尖位置数据（用于气化判断）
            tooth_apex_positions = self._extract_tooth_apex_positions(
                teeth_results, UPPER_POSTERIOR_TEETH, h, w
            )
            logger.info(f"Extracted apex positions for {len(tooth_apex_positions)} upper posterior teeth: {list(tooth_apex_positions.keys())}")
            
            # 调试：打印检测到的所有牙齿FDI
            if teeth_results:
                detected_teeth = teeth_results.get("detected_teeth", [])
                all_fdi = [t.get("fdi") for t in detected_teeth]
                logger.info(f"[DEBUG] All detected teeth FDI: {all_fdi}")
                upper_posterior_fdi = [f for f in all_fdi if f in ["14","15","16","17","18","24","25","26","27","28"]]
                logger.info(f"[DEBUG] Upper posterior teeth in detection: {upper_posterior_fdi}")

            # 获取比例尺（默认 0.1 mm/pixel）
            scale_y = 0.1  # 垂直方向比例尺
            if pixel_spacing:
                scale_y = pixel_spacing.get("scale_y", pixel_spacing.get("scale_x", 0.1))
            logger.info(f"Using pixel spacing scale_y={scale_y} mm/pixel for pneumatization calculation")

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

                # 提取该连通域的 mask
                side_mask = (labels == component_index).astype(np.uint8)

                # 5. 计算上颌窦底位置（该侧 mask 的最低点 y 坐标）
                sinus_bottom_y = self._find_sinus_bottom(side_mask)
                logger.info(f"{location} sinus bottom Y position: {sinus_bottom_y}")

                # 6. 气化判断：计算与该侧上颌后牙根尖的距离
                # 传递整个 side_mask 用于检测牙齿与上颌窦的空间交集
                pneumatization_type, root_entry_teeth, min_distance_mm = self._calculate_pneumatization(
                    side_lower, side_mask, tooth_apex_positions, 
                    UPPER_POSTERIOR_TEETH, scale_y
                )
                
                logger.info(f"{location} sinus pneumatization: Type={pneumatization_type}, "
                           f"MinDistance={min_distance_mm:.2f}mm, RootEntryTeeth={root_entry_teeth}")

                # 提取轮廓坐标
                contour_coords = []
                try:
                    contours, _ = cv2.findContours(
                        side_mask,
                        cv2.RETR_EXTERNAL,
                        cv2.CHAIN_APPROX_SIMPLE
                    )
                    if contours:
                        largest_contour = max(contours, key=cv2.contourArea)
                        epsilon = 0.005 * cv2.arcLength(largest_contour, True)
                        approx_contour = cv2.approxPolyDP(largest_contour, epsilon, True)

                        coords = approx_contour.squeeze()
                        if coords.ndim == 1:
                            contour_coords = [[int(coords[0]), int(coords[1])]]
                        else:
                            contour_coords = [[int(pt[0]), int(pt[1])] for pt in coords]

                        logger.info(f"Extracted {len(contour_coords)} contour points for {location} sinus")
                except Exception as e:
                    logger.warning(f"Failed to extract contour for {location} sinus: {e}")

                # 裁剪 ROI (加 Padding)
                pad = 30
                x1, y1 = max(0, x - pad), max(0, y - pad)
                x2, y2 = min(w, x + sw + pad), min(h, y + sh + pad)
                crop = image[y1:y2, x1:x2]

                # 7. 分类 (Sinus Class) - 炎症判断
                is_inflam = False
                conf = 0.0

                if crop.size > 0:
                    logger.info(f"Classifying {location} sinus ROI...")
                    cls_res = self.modules['sinus_class'].predict(crop)
                    is_inflam = cls_res.get('is_inflam', False)
                    conf = cls_res.get('confidence', 0.0)
                else:
                    logger.warning(f"Invalid crop for {location} sinus.")

                # 8. 构造详细描述
                cn_side = "左" if side_lower == 'left' else "右"
                detail = self._generate_sinus_detail(
                    cn_side, pneumatization_type, is_inflam, 
                    root_entry_teeth, min_distance_mm
                )

                results_list.append({
                    "Side": side_lower,
                    "Pneumatization": pneumatization_type,  # 1=I型, 2=II型, 3=III型
                    "TypeClassification": pneumatization_type,
                    "Inflammation": is_inflam,
                    "RootEntryToothFDI": root_entry_teeth,  # 进入上颌窦的牙齿序列号
                    "Detail": detail,
                    "Confidence_Pneumatization": 0.85 if tooth_apex_positions else 0.5,
                    "Confidence_Inflammation": float(f"{conf:.2f}")
                })
                
                # 包含 contour 用于前端可视化
                if contour_coords and len(contour_coords) >= 3:
                    masks_info.append({
                        "label": f"sinus_{side_lower}",
                        "bbox": [int(x), int(y), int(sw), int(sh)],
                        "contour": contour_coords
                    })
                    logger.info(f"Added {location} sinus to masks_info with {len(contour_coords)} points")
                else:
                    logger.warning(f"Skipping {location} sinus masks_info: contour too small")
            
            elapsed = time.time() - start_time
            logger.info(f"Sinus workflow completed in {elapsed:.2f}s")

            return {"MaxillarySinus": results_list, "masks_info": masks_info}

        except Exception as e:
            logger.error(f"Sinus workflow failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}

    def _extract_tooth_apex_positions(
        self, 
        teeth_results: dict, 
        upper_posterior_teeth: dict,
        image_h: int,
        image_w: int
    ) -> dict:
        """
        从牙齿分割结果中提取上颌后牙的根尖位置

        Args:
            teeth_results: 牙齿分割结果
            upper_posterior_teeth: 上颌后牙 FDI 定义（按侧别）
            image_h: 图像高度
            image_w: 图像宽度

        Returns:
            dict: FDI -> {
                'apex_y': y坐标, 
                'apex_x': 根尖x坐标,
                'x_min': 牙齿mask最左x坐标,
                'x_max': 牙齿mask最右x坐标,
                'side': 'left'/'right',
                'mask': 缩放后的牙齿mask (用于交集检测)
            }
            apex_y 是根尖的 y 坐标（y 值越大，位置越靠下/靠近上颌窦底）
        """
        apex_positions = {}

        if not teeth_results:
            logger.warning("[_extract_tooth_apex_positions] No teeth_results provided")
            return apex_positions

        detected_teeth = teeth_results.get("detected_teeth", [])
        raw_masks = teeth_results.get("raw_masks", None)
        original_shape = teeth_results.get("original_shape", None)

        if raw_masks is None or len(detected_teeth) == 0:
            logger.warning("[_extract_tooth_apex_positions] No valid teeth masks")
            return apex_positions

        # 获取 mask 尺寸并计算缩放因子
        if isinstance(raw_masks, np.ndarray) and raw_masks.ndim == 3:
            mask_h, mask_w = raw_masks.shape[1], raw_masks.shape[2]
        elif isinstance(raw_masks, list) and len(raw_masks) > 0:
            first_mask = raw_masks[0]
            if isinstance(first_mask, np.ndarray):
                mask_h, mask_w = first_mask.shape[:2]
            else:
                logger.warning("[_extract_tooth_apex_positions] First mask is not ndarray")
                return apex_positions
        else:
            logger.warning("[_extract_tooth_apex_positions] raw_masks format not recognized")
            return apex_positions

        # 计算缩放因子
        scale_x, scale_y = 1.0, 1.0
        if original_shape and len(original_shape) >= 2:
            orig_h, orig_w = original_shape[0], original_shape[1]
            scale_x = orig_w / mask_w
            scale_y = orig_h / mask_h
        
        logger.info(f"[_extract_tooth_apex_positions] mask_shape=({mask_h}, {mask_w}), "
                   f"original_shape={original_shape}, target_image=({image_h}, {image_w}), "
                   f"scale_factors: x={scale_x:.3f}, y={scale_y:.3f}")

        # 所有上颌后牙 FDI
        all_upper_posterior_fdi = set()
        for side, fdi_list in upper_posterior_teeth.items():
            for fdi in fdi_list:
                all_upper_posterior_fdi.add(fdi)

        # 遍历检测到的牙齿
        for tooth in detected_teeth:
            fdi = tooth.get("fdi")
            if not fdi or fdi not in all_upper_posterior_fdi:
                continue

            mask_idx = tooth.get("mask_index", -1)
            if mask_idx < 0:
                continue

            # 获取对应的 mask
            if isinstance(raw_masks, np.ndarray) and raw_masks.ndim == 3:
                if mask_idx >= raw_masks.shape[0]:
                    continue
                mask = raw_masks[mask_idx]
            elif isinstance(raw_masks, list):
                if mask_idx >= len(raw_masks):
                    continue
                mask = raw_masks[mask_idx]
            else:
                continue

            if not isinstance(mask, np.ndarray):
                continue

            try:
                ys, xs = np.where(mask > 0.5)
                if ys.size == 0:
                    continue

                # 根尖位置：
                # 上颌牙根尖朝上 → 在图像坐标系中 y 值**最小**的位置
                # （图像坐标系中 y 增大是向下的）
                # 注意：这里处理的是上颌后牙，所以取 ys.min()
                apex_y_mask = int(ys.min())
                
                # 提取根尖区域（取y最小处对应的x范围的中点作为根尖x坐标）
                apex_region_xs = xs[ys == apex_y_mask]
                apex_x_mask = int(np.mean(apex_region_xs)) if len(apex_region_xs) > 0 else int(xs.mean())
                
                # 缩放到原图坐标
                apex_y = apex_y_mask * scale_y
                apex_x = apex_x_mask * scale_x
                x_min = int(xs.min() * scale_x)
                x_max = int(xs.max() * scale_x)

                # 判断该牙属于哪一侧
                side = None
                for s, fdi_list in upper_posterior_teeth.items():
                    if fdi in fdi_list:
                        side = s
                        break

                # 缩放 mask 到原图大小（用于后续交集检测）
                scaled_mask = None
                if scale_x != 1.0 or scale_y != 1.0:
                    scaled_mask = cv2.resize(
                        (mask > 0.5).astype(np.uint8), 
                        (image_w, image_h), 
                        interpolation=cv2.INTER_NEAREST
                    )
                else:
                    scaled_mask = (mask > 0.5).astype(np.uint8)

                apex_positions[fdi] = {
                    'apex_y': apex_y,
                    'apex_x': apex_x,
                    'x_min': x_min,
                    'x_max': x_max,
                    'side': side,
                    'mask': scaled_mask
                }
                logger.debug(f"[_extract_tooth_apex_positions] Tooth {fdi}: apex_y={apex_y:.1f}, apex_x={apex_x:.1f}, x_range=[{x_min}, {x_max}], side={side}")

            except Exception as exc:
                logger.warning(f"[_extract_tooth_apex_positions] Failed to extract apex for tooth {fdi}: {exc}")

        return apex_positions

    def _find_sinus_bottom(self, sinus_mask: np.ndarray) -> int:
        """
        找到上颌窦 mask 的底部 y 坐标

        Args:
            sinus_mask: 上颌窦的二值 mask

        Returns:
            int: 上颌窦底部的 y 坐标（y 越大越靠下）
        """
        ys, _ = np.where(sinus_mask > 0)
        if ys.size == 0:
            return 0
        return int(ys.max())

    def _calculate_pneumatization(
        self,
        side: str,
        sinus_mask: np.ndarray,
        tooth_apex_positions: dict,
        upper_posterior_teeth: dict,
        scale_y: float
    ) -> tuple:
        """
        计算上颌窦气化类型

        算法核心：
            计算每颗上颌后牙根尖到上颌窦底部的**垂直距离**。
            对于每颗牙，找到该牙X范围内上颌窦的局部底部Y坐标，
            然后计算：距离 = 窦底Y - 根尖Y
            - 距离 > 0: 根尖在窦底上方（未进入）
            - 距离 < 0: 根尖在窦底下方（已进入）

        气化分型标准：
            - Ⅰ型: 距离 > 3mm（正常/未气化）
            - Ⅱ型: 0 ≤ 距离 ≤ 3mm（显著气化）
            - Ⅲ型: 距离 < 0mm（过度气化，牙根进入窦内）

        Args:
            side: 'left' 或 'right'
            sinus_mask: 该侧上颌窦的二值 mask
            tooth_apex_positions: 牙齿根尖位置字典
            upper_posterior_teeth: 上颌后牙 FDI 定义
            scale_y: 垂直方向比例尺（mm/pixel）

        Returns:
            tuple: (气化类型, 进入上颌窦的牙齿列表, 最小距离mm)
        """
        if sinus_mask is None or not tooth_apex_positions:
            logger.warning("[_calculate_pneumatization] Missing sinus_mask or tooth data")
            return 0, [], float('inf')

        sinus_binary = (sinus_mask > 0).astype(np.uint8)
        if np.sum(sinus_binary) == 0:
            logger.warning("[_calculate_pneumatization] Empty sinus mask")
            return 0, [], float('inf')

        h, w = sinus_mask.shape
        side_teeth_fdi = upper_posterior_teeth.get(side, [])
        min_distance_mm = float('inf')
        root_entry_teeth = []
        
        # 获取上颌窦的全局范围
        sinus_ys, sinus_xs = np.where(sinus_binary > 0)
        sinus_x_min, sinus_x_max = int(sinus_xs.min()), int(sinus_xs.max())
        sinus_y_max = int(sinus_ys.max())  # 全局窦底Y
        
        logger.info(f"[_calculate_pneumatization] side={side}, sinus range: x=[{sinus_x_min}, {sinus_x_max}], "
                   f"global_bottom_y={sinus_y_max}, teeth to check: {side_teeth_fdi}, "
                   f"available positions: {list(tooth_apex_positions.keys())}")

        for fdi in side_teeth_fdi:
            apex_info = tooth_apex_positions.get(fdi)
            if not apex_info:
                logger.debug(f"[_calculate_pneumatization] Tooth {fdi}: NOT FOUND in apex_positions")
                continue
            if apex_info.get('side') != side:
                logger.debug(f"[_calculate_pneumatization] Tooth {fdi}: side mismatch")
                continue

            # 获取根尖坐标
            apex_y = apex_info['apex_y']
            apex_x = apex_info.get('apex_x', 0)
            tooth_x_min = apex_info.get('x_min', int(apex_x) - 20)
            tooth_x_max = apex_info.get('x_max', int(apex_x) + 20)
            
            # 检查牙齿X范围是否与上颌窦有重叠
            if tooth_x_max < sinus_x_min or tooth_x_min > sinus_x_max:
                logger.debug(f"[_calculate_pneumatization] Tooth {fdi}: no X overlap with sinus")
                continue
            
            # 计算该牙齿X范围内的上颌窦局部底部Y坐标
            x_start = max(0, tooth_x_min)
            x_end = min(w, tooth_x_max + 1)
            local_region = sinus_binary[:, x_start:x_end]
            local_ys, _ = np.where(local_region > 0)
            
            if local_ys.size == 0:
                # 该牙齿X范围内没有上颌窦，使用全局窦底
                local_sinus_bottom_y = sinus_y_max
            else:
                local_sinus_bottom_y = int(local_ys.max())
            
            # 计算垂直距离（像素）
            # 图像坐标系：y=0在顶部，y增大向下
            # 上颌后牙根尖朝上（y值小），窦底是窦的下边界（y值大）
            # 距离 = 根尖Y - 窦底Y
            # > 0: 根尖在窦底下方（有骨质间隙，正常）
            # < 0: 根尖在窦底上方（进入窦内，异常）
            distance_pixels = apex_y - local_sinus_bottom_y
            distance_mm = distance_pixels * scale_y

            logger.info(f"[_calculate_pneumatization] Tooth {fdi}: apex=({apex_x:.0f}, {apex_y:.0f}), "
                       f"local_sinus_bottom_y={local_sinus_bottom_y}, "
                       f"distance_pixels={distance_pixels:.1f}, distance_mm={distance_mm:.2f}mm")

            # 更新最小距离
            min_distance_mm = min(min_distance_mm, distance_mm)

            # 距离 < 0 表示根尖在窦底上方（牙根进入上颌窦）
            if distance_mm < 0:
                root_entry_teeth.append(fdi)
                logger.info(f"[_calculate_pneumatization] Tooth {fdi}: ROOT ENTERS SINUS (distance={distance_mm:.2f}mm)")

        # 气化类型判断
        # Ⅰ型: 距离 > 3mm（正常）
        # Ⅱ型: 0 ≤ 距离 ≤ 3mm（显著气化）
        # Ⅲ型: 距离 < 0mm（过度气化，牙根进入窦内）
        if min_distance_mm == float('inf'):
            pneumatization_type = 0
            logger.info(f"[_calculate_pneumatization] Result: Type=0 (no valid teeth data)")
        elif min_distance_mm < 0:
            pneumatization_type = 3  # III型：过度气化
            logger.info(f"[_calculate_pneumatization] Result: Type=3 (III型过度气化), min_distance={min_distance_mm:.2f}mm")
        elif min_distance_mm <= 3:
            pneumatization_type = 2  # II型：显著气化
            logger.info(f"[_calculate_pneumatization] Result: Type=2 (II型显著气化), min_distance={min_distance_mm:.2f}mm")
        else:
            pneumatization_type = 1  # I型：正常
            logger.info(f"[_calculate_pneumatization] Result: Type=1 (I型正常), min_distance={min_distance_mm:.2f}mm")

        return pneumatization_type, root_entry_teeth, min_distance_mm

    def _generate_sinus_detail(
        self,
        cn_side: str,
        pneumatization_type: int,
        is_inflam: bool,
        root_entry_teeth: list,
        min_distance_mm: float
    ) -> str:
        """
        生成上颌窦详细描述

        Args:
            cn_side: "左" 或 "右"
            pneumatization_type: 气化类型 (0/1/2/3)
            is_inflam: 是否有炎症
            root_entry_teeth: 进入上颌窦的牙齿列表
            min_distance_mm: 最小距离 (mm)

        Returns:
            str: 详细描述文本
        """
        parts = [f"{cn_side}上颌窦"]

        # 气化类型描述
        if pneumatization_type == 1:
            parts.append("气化正常（I型）")
        elif pneumatization_type == 2:
            if min_distance_mm != float('inf'):
                parts.append(f"显著气化（II型，窦底与根尖距离约{min_distance_mm:.1f}mm）")
            else:
                parts.append("显著气化（II型）")
        elif pneumatization_type == 3:
            parts.append("过度气化（III型）")
            if root_entry_teeth:
                teeth_str = "、".join(root_entry_teeth)
                parts.append(f"，牙位{teeth_str}根尖进入上颌窦")
        else:
            parts.append("气化状态待评估")

        # 炎症描述
        if is_inflam:
            parts.append("。可见炎症影像，局部存在充满窦腔的模糊影像，疑似积液或囊肿，建议耳鼻喉科会诊")
        else:
            if pneumatization_type in [1, 2]:
                parts.append("，窦腔清晰")
            parts.append("。")

        return "".join(parts)

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
    def _analyze_teeth_and_attributes(
            self,
            teeth_results: dict,
            teeth_attr1: dict,
            teeth_attr2: dict,
            curved_short_root: dict,
            erupted_wisdomteeth: dict,
            iou_threshold: float = 0.5,
    ) -> dict:
        """
        牙位-属性绑定、缺失牙、智齿状态分析

        修复：将牙齿 mask 坐标缩放到原图坐标系
        """
        from collections import defaultdict
        import numpy as np

        logger.info("=" * 60)
        logger.info("[DEBUG] _analyze_teeth_and_attributes 开始")
        logger.info("=" * 60)

        # ------------------------------------------------------------------
        # 1. 从分割 mask 计算每颗牙的 bbox，并缩放到原图坐标系
        # ------------------------------------------------------------------
        detected_teeth = teeth_results.get("detected_teeth", [])
        raw_masks = teeth_results.get("raw_masks", None)

        # 获取原图尺寸（从 teeth_results 或属性模块中获取）
        # 尝试从 teeth_results 获取
        original_image_shape = teeth_results.get("image_shape", None)

        # 如果没有，尝试从属性模块获取
        if original_image_shape is None:
            for attr_res in [teeth_attr1, teeth_attr2, curved_short_root, erupted_wisdomteeth]:
                if attr_res and "image_shape" in attr_res:
                    original_image_shape = attr_res["image_shape"]
                    break

        # 如果还是没有，尝试从 original_shape 字段获取
        if original_image_shape is None:
            original_image_shape = teeth_results.get("original_shape", None)

        logger.info(f"[DEBUG] detected_teeth count: {len(detected_teeth)}")
        logger.info(f"[DEBUG] original_image_shape: {original_image_shape}")

        tooth_bboxes = {}  # FDI -> [x1,y1,x2,y2] (原图坐标系)

        if raw_masks is None or len(detected_teeth) == 0:
            logger.warning("[_analyze_teeth_and_attributes] 无有效的牙齿分割结果，跳过牙齿属性分析")
        else:
            # 获取 mask 的尺寸
            if isinstance(raw_masks, np.ndarray):
                if raw_masks.ndim == 3:
                    mask_h, mask_w = raw_masks.shape[1], raw_masks.shape[2]
                elif raw_masks.ndim == 2:
                    mask_h, mask_w = raw_masks.shape
                else:
                    mask_h, mask_w = None, None
            elif isinstance(raw_masks, list) and len(raw_masks) > 0:
                first_mask = raw_masks[0]
                if isinstance(first_mask, np.ndarray):
                    mask_h, mask_w = first_mask.shape[:2]
                else:
                    mask_h, mask_w = None, None
            else:
                mask_h, mask_w = None, None

            logger.info(f"[DEBUG] mask 尺寸: H={mask_h}, W={mask_w}")

            # 计算缩放因子
            scale_x, scale_y = 1.0, 1.0
            if original_image_shape is not None and mask_h is not None and mask_w is not None:
                # original_image_shape 通常是 (H, W) 或 (H, W, C)
                if isinstance(original_image_shape, (list, tuple)):
                    if len(original_image_shape) >= 2:
                        orig_h, orig_w = original_image_shape[0], original_image_shape[1]
                        scale_x = orig_w / mask_w
                        scale_y = orig_h / mask_h
                        logger.info(f"[DEBUG] 原图尺寸: H={orig_h}, W={orig_w}")
                        logger.info(f"[DEBUG] 缩放因子: scale_x={scale_x:.4f}, scale_y={scale_y:.4f}")
            else:
                # 如果无法获取原图尺寸，尝试通过常见的推理尺寸反推
                # YOLO 常用 640x640 或 640xH，原图可能是 2356x1292
                # 这里设置一个警告，并尝试一个合理的默认值
                logger.warning("[DEBUG] 无法获取原图尺寸，尝试从属性框坐标反推...")

                # 从属性框的最大坐标估算原图尺寸
                max_x, max_y = 0, 0
                for attr_res in [teeth_attr1, teeth_attr2, curved_short_root, erupted_wisdomteeth]:
                    if attr_res and "boxes" in attr_res:
                        boxes = attr_res["boxes"]
                        for box in boxes:
                            if isinstance(box, (list, tuple, np.ndarray)) and len(box) >= 4:
                                max_x = max(max_x, float(box[2]))
                                max_y = max(max_y, float(box[3]))

                if max_x > 0 and max_y > 0 and mask_w is not None and mask_h is not None:
                    # 估算原图尺寸（取属性框的最大坐标并加一些余量）
                    estimated_orig_w = max_x * 1.1  # 加10%余量
                    estimated_orig_h = max_y * 1.1
                    scale_x = estimated_orig_w / mask_w
                    scale_y = estimated_orig_h / mask_h
                    logger.warning(f"[DEBUG] 估算原图尺寸: W≈{estimated_orig_w:.0f}, H≈{estimated_orig_h:.0f}")
                    logger.warning(f"[DEBUG] 估算缩放因子: scale_x={scale_x:.4f}, scale_y={scale_y:.4f}")

            # 遍历牙齿，计算 bbox 并缩放
            for tooth in detected_teeth:
                fdi = tooth.get("fdi")
                mask_idx = tooth.get("mask_index", -1)

                if not fdi:
                    continue
                if mask_idx < 0:
                    continue

                # 获取对应的 mask
                if isinstance(raw_masks, np.ndarray) and raw_masks.ndim == 3:
                    if mask_idx >= raw_masks.shape[0]:
                        continue
                    mask = raw_masks[mask_idx]
                elif isinstance(raw_masks, list):
                    if mask_idx >= len(raw_masks):
                        continue
                    mask = raw_masks[mask_idx]
                else:
                    continue

                if not isinstance(mask, np.ndarray):
                    continue

                try:
                    ys, xs = np.where(mask > 0.5)
                    if ys.size == 0 or xs.size == 0:
                        continue

                    # mask 坐标系下的 bbox
                    x1_mask, y1_mask = int(xs.min()), int(ys.min())
                    x2_mask, y2_mask = int(xs.max()), int(ys.max())

                    # 缩放到原图坐标系
                    x1 = x1_mask * scale_x
                    y1 = y1_mask * scale_y
                    x2 = x2_mask * scale_x
                    y2 = y2_mask * scale_y

                    tooth_bboxes[fdi] = [x1, y1, x2, y2]

                except Exception as exc:
                    logger.warning(f"[_analyze_teeth_and_attributes] 计算牙位 {fdi} bbox 失败: {exc}")

        logger.info(
            f"[_analyze_teeth_and_attributes] detected_teeth={len(detected_teeth)}, valid_bboxes={len(tooth_bboxes)}")

        # 调试：打印一些 bbox 样例
        if tooth_bboxes:
            sample_items = list(tooth_bboxes.items())[:3]
            for fdi, bbox in sample_items:
                logger.info(
                    f"[DEBUG] 缩放后牙齿 [{fdi}] bbox: [{bbox[0]:.1f}, {bbox[1]:.1f}, {bbox[2]:.1f}, {bbox[3]:.1f}]")

        # ------------------------------------------------------------------
        # 2. 收集所有属性检测框
        # ------------------------------------------------------------------
        all_attr_boxes = []  # [(bbox, attribute_name), ...]

        # 从 teeth_attr1 提取属性框
        if teeth_attr1:
            boxes = teeth_attr1.get("boxes", [])
            attr_names = teeth_attr1.get("attribute_names", [])
            # 兼容旧格式
            if not attr_names:
                attributes_detected = teeth_attr1.get("attributes_detected", [])
                for i, attr_info in enumerate(attributes_detected):
                    if i < len(boxes):
                        attr_name = attr_info.get("attribute", "unknown")
                        all_attr_boxes.append((boxes[i], attr_name))
            else:
                for i, box in enumerate(boxes):
                    if i < len(attr_names):
                        all_attr_boxes.append((box, attr_names[i]))

        # 从 teeth_attr2 提取属性框
        if teeth_attr2:
            boxes = teeth_attr2.get("boxes", [])
            attr_names = teeth_attr2.get("attribute_names", [])
            if isinstance(boxes, np.ndarray):
                boxes = boxes.tolist()
            for i, box in enumerate(boxes):
                if i < len(attr_names):
                    all_attr_boxes.append((box, attr_names[i]))

        # 从 curved_short_root 提取属性框
        if curved_short_root:
            boxes = curved_short_root.get("boxes", [])
            attr_names = curved_short_root.get("attribute_names", [])
            if isinstance(boxes, np.ndarray):
                boxes = boxes.tolist()
            for i, box in enumerate(boxes):
                if i < len(attr_names):
                    all_attr_boxes.append((box, attr_names[i]))

        # 从 erupted_wisdomteeth 提取属性框
        if erupted_wisdomteeth:
            boxes = erupted_wisdomteeth.get("boxes", [])
            attr_names = erupted_wisdomteeth.get("attribute_names", [])
            if isinstance(boxes, np.ndarray):
                boxes = boxes.tolist()
            for i, box in enumerate(boxes):
                if i < len(attr_names):
                    all_attr_boxes.append((box, attr_names[i]))

        logger.info(f"[DEBUG] 收集到 {len(all_attr_boxes)} 个属性框")

        # ------------------------------------------------------------------
        # 3. IoU 匹配：属性框 -> 牙齿
        # ------------------------------------------------------------------
        tooth_attributes = defaultdict(set)  # FDI -> set of attribute names

        def bbox_iou(box1, box2) -> float:
            """计算两个 bbox 的 IoU"""
            x1, y1, x2, y2 = box1
            x1g, y1g, x2g, y2g = box2
            inter_x1 = max(x1, x1g)
            inter_y1 = max(y1, y1g)
            inter_x2 = min(x2, x2g)
            inter_y2 = min(y2, y2g)
            inter_w = max(0.0, inter_x2 - inter_x1)
            inter_h = max(0.0, inter_y2 - inter_y1)
            inter_area = inter_w * inter_h
            area1 = max(0.0, x2 - x1) * max(0.0, y2 - y1)
            area2 = max(0.0, x2g - x1g) * max(0.0, y2g - y1g)
            if area1 <= 0 or area2 <= 0:
                return 0.0
            union = area1 + area2 - inter_area
            return inter_area / union if union > 0 else 0.0

        for attr_box, attr_name in all_attr_boxes:
            best_fdi = None
            best_iou = 0.0
            for fdi, tooth_box in tooth_bboxes.items():
                iou = bbox_iou(attr_box, tooth_box)
                if iou > best_iou:
                    best_iou = iou
                    best_fdi = fdi

            if best_fdi and best_iou >= iou_threshold:
                tooth_attributes[best_fdi].add(attr_name)
                logger.debug(f"[DEBUG] 属性 '{attr_name}' 匹配到牙齿 {best_fdi}，IoU={best_iou:.3f}")
            elif best_fdi:
                logger.debug(f"[DEBUG] 属性 '{attr_name}' 最佳匹配 {best_fdi}，但 IoU={best_iou:.3f} < {iou_threshold}")

        logger.info(f"[DEBUG] 成功匹配属性的牙齿数: {len(tooth_attributes)}")

        # ------------------------------------------------------------------
        # 4. 分析缺失牙
        # ------------------------------------------------------------------
        detected_fdi_set = set(tooth_bboxes.keys())
        missing_teeth = []

        for fdi in ALL_PERMANENT_TEETH_FDI:
            if fdi not in detected_fdi_set:
                # 排除智齿（智齿缺失不算缺牙）
                if fdi not in WISDOM_TEETH_FDI:
                    missing_teeth.append({
                        "FDI": fdi,
                        "Reason": "missing",
                        "Detail": f"牙位 {fdi} 未检测到"
                    })

        logger.info(f"[DEBUG] 缺失牙数量: {len(missing_teeth)}")

        # ------------------------------------------------------------------
        # 5. 分析智齿状态 (ThirdMolarSummary)
        # ------------------------------------------------------------------
        third_molar_summary = {}

        for fdi in WISDOM_TEETH_FDI:
            if fdi in detected_fdi_set:
                attrs = tooth_attributes.get(fdi, set())
                # 判断智齿状态
                if "erupted" in attrs:
                    # 已萌出
                    third_molar_summary[fdi] = {
                        "Level": 0,
                        "Impactions": None,
                        "Detail": "已萌出",
                        "Confidence": 0.85
                    }
                elif "wisdom_tooth_impaction" in attrs or "impacted" in attrs:
                    # 阻生
                    third_molar_summary[fdi] = {
                        "Level": 1,
                        "Impactions": "Impacted",
                        "Detail": "阻生",
                        "Confidence": 0.85
                    }
                else:
                    # 已检测到但状态未知，默认视为存在
                    third_molar_summary[fdi] = {
                        "Level": 2,
                        "Impactions": None,
                        "Detail": "已检测到",
                        "Confidence": 0.70
                    }
            else:
                # 未检测到智齿
                third_molar_summary[fdi] = {
                    "Level": 4,
                    "Impactions": None,
                    "Detail": "未见智齿",
                    "Confidence": 0.0
                }

        logger.info(f"[DEBUG] 智齿状态分析完成: {list(third_molar_summary.keys())}")

        # ------------------------------------------------------------------
        # 6. 返回结果
        # ------------------------------------------------------------------
        result = {
            "MissingTeeth": missing_teeth,
            "ThirdMolarSummary": third_molar_summary,
            "ToothAttributes": {fdi: list(attrs) for fdi, attrs in tooth_attributes.items()}
        }

        logger.info("=" * 60)
        logger.info("[DEBUG] _analyze_teeth_and_attributes 完成")
        logger.info(f"[DEBUG] 结果: MissingTeeth={len(missing_teeth)}, "
                    f"ThirdMolarSummary={len(third_molar_summary)}, "
                    f"ToothAttributes={len(tooth_attributes)}")
        logger.info("=" * 60)

        return result

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
            "teeth_attribute1": module_results.get("teeth_attribute1", {}),
            "teeth_attribute2": module_results.get("teeth_attribute2", {}),
            "curved_short_root": module_results.get("curved_short_root", {}),
            "erupted_wisdomteeth": module_results.get("erupted_wisdomteeth", {}),
            "sinus": module_results.get("sinus", {}),  # 收集上颌窦结果
            "rootTipDensity": module_results.get("rootTipDensity", {}),  # 收集根尖低密度影结果
        }

        return inference_results
