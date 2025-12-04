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

# 导入原有五个模块的预测器
from pipelines.pano.modules.condyle_seg import JointPredictor as CondyleSegPredictor
from pipelines.pano.modules.condyle_detection import JointPredictor as CondyleDetPredictor
from pipelines.pano.modules.mandible_seg import MandiblePredictor
from pipelines.pano.modules.implant_detect import ImplantDetectionModule
from pipelines.pano.modules.teeth_seg import TeethSegmentationModule, process_teeth_results

# 导入重构后的上颌窦模块预测器
# 假设您已经按照建议重构了这两个文件，分别只负责分割和分类
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

            # 2.6 牙齿属性检测1
            teeth_attribute1_results = self._run_teeth_attribute1(image_path)

            # 2.7 牙齿属性检测2
            teeth_attribute2_results = self._run_teeth_attribute2(image_path)

            # 2.8 牙齿属性检测3-压根形态弯曲短小
            curved_short_root_results = self._run_curved_short_root(image_path)

            # 2.9 牙齿属性检测4-智齿已萌出
            erupted_wisdomteeth_results = self._run_erupted_wisdomteeth(image_path)

            # 2.10 上颌窦分析 (分割 + 分类)
            sinus_results = self._run_sinus_workflow(image_path)

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
            teeth_attribute1=teeth_attribute1_results,
            teeth_attribute2=teeth_attribute2_results,
            curved_short_root=curved_short_root_results,
            erupted_wisdomteeth=erupted_wisdomteeth_results,
            sinus=sinus_results,  # 加入上颌窦结果
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
            logger.info("Running Sinus Segmentation...")
            seg_res = self.modules['sinus_seg'].predict(image)
            mask_full = seg_res.get('mask')  # 预期 Seg 模块返回 {'mask': np.array}

            if mask_full is None:
                logger.warning("Sinus segmentation returned no mask.")
                return {}

            # 3. 连通域分析 (获取左右侧 ROI)
            # 使用 8 连通性
            num, labels, stats, centroids = cv2.connectedComponentsWithStats(mask_full, connectivity=8)

            results_list = []
            masks_info = []

            logger.info(f"Found {num - 1} sinus components.")

            for i in range(1, num):
                # 过滤小面积噪点
                if stats[i, cv2.CC_STAT_AREA] < 500: continue

                # 获取位置信息
                x, y, sw, sh = stats[i][:4]
                cx = centroids[i][0]
                # 判定左右侧：图像左侧 = 患者右侧
                location = "Right" if cx < (w / 2) else "Left"
                side_lower = location.lower()

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

                masks_info.append({
                    "label": f"sinus_{side_lower}",
                    "bbox": [int(x), int(y), int(sw), int(sh)]
                })

            elapsed = time.time() - start_time
            logger.info(f"Sinus workflow completed in {elapsed:.2f}s")

            return {"MaxillarySinus": results_list, "masks_info": masks_info}

        except Exception as e:
            logger.error(f"Sinus workflow failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}

    # ---------------------------------------------------------------------
    # 牙齿 + 属性综合分析（牙位-属性绑定、缺失牙、智齿状态）
    # ---------------------------------------------------------------------

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
        # 2. 聚合四个属性模块的检测框
        # ------------------------------------------------------------------
        def _gather_from_module(module_res: dict, module_name: str) -> list:
            boxes = module_res.get("boxes")
            names = module_res.get("attribute_names")

            if boxes is None or names is None:
                return []

            if len(boxes) == 0 or len(names) == 0:
                return []

            n = min(len(boxes), len(names))
            dets = []
            for i in range(n):
                box = boxes[i]
                cls_name = names[i]
                try:
                    if isinstance(box, np.ndarray):
                        box = box.tolist()
                    if isinstance(box, (list, tuple)) and len(box) >= 4:
                        box_list = [float(box[0]), float(box[1]), float(box[2]), float(box[3])]
                    else:
                        continue
                except Exception:
                    continue
                dets.append({
                    "bbox": box_list,
                    "class_name": cls_name,
                    "confidence": 0.9,
                })

            return dets

        attribute_detections = []
        attribute_detections.extend(_gather_from_module(teeth_attr1 or {}, "teeth_attr1"))
        attribute_detections.extend(_gather_from_module(teeth_attr2 or {}, "teeth_attr2"))
        attribute_detections.extend(_gather_from_module(curved_short_root or {}, "curved_short_root"))
        attribute_detections.extend(_gather_from_module(erupted_wisdomteeth or {}, "erupted_wisdomteeth"))

        logger.info(f"[_analyze_teeth_and_attributes] total attribute boxes gathered={len(attribute_detections)}")

        # 调试：打印一些属性框样例
        if attribute_detections:
            for det in attribute_detections[:3]:
                bbox = det["bbox"]
                logger.info(
                    f"[DEBUG] 属性 [{det['class_name']}] bbox: [{bbox[0]:.1f}, {bbox[1]:.1f}, {bbox[2]:.1f}, {bbox[3]:.1f}]")

        # ------------------------------------------------------------------
        # 3. 牙位-属性绑定 (IoU)
        # ------------------------------------------------------------------
        tooth_attributes = defaultdict(list)

        def _bbox_iou_xyxy(box1, box2) -> float:
            x1, y1, x2, y2 = box1
            x1g, y1g, x2g, y2g = box2
            inter_x1 = max(x1, x1g)
            inter_y1 = max(y1, y1g)
            inter_x2 = min(x2, x2g)
            inter_y2 = min(y2, y2g)
            inter_w = max(0.0, inter_x2 - inter_x1)
            inter_h = max(0.0, inter_y2 - inter_y1)
            inter_area = inter_w * inter_h
            if inter_area <= 0:
                return 0.0
            area1 = max(0.0, x2 - x1) * max(0.0, y2 - y1)
            area2 = max(0.0, x2g - x1g) * max(0.0, y2g - y1g)
            if area1 <= 0 or area2 <= 0:
                return 0.0
            union = area1 + area2 - inter_area
            if union <= 0:
                return 0.0
            return inter_area / union

        filtered_attributes = [
            attr for attr in attribute_detections
            if float(attr.get("confidence", 0.0)) >= CONF_THRESHOLD
        ]

        # 调试：统计 IoU > 0.01 的次数
        iou_positive_count = 0
        for attr in filtered_attributes:
            attr_box = attr["bbox"]
            for fdi, tooth_box in tooth_bboxes.items():
                iou = _bbox_iou_xyxy(attr_box, tooth_box)
                if iou > 0.01:
                    iou_positive_count += 1

        logger.info(f"[DEBUG] IoU > 0.01 的重叠次数: {iou_positive_count}")

        # 执行绑定
        for attr in filtered_attributes:
            attr_box = attr["bbox"]
            attr_name = attr["class_name"]
            attr_conf = float(attr.get("confidence", 0.0))

            best_fdi = None
            best_iou = 0.0
            for fdi, tooth_box in tooth_bboxes.items():
                iou = _bbox_iou_xyxy(attr_box, tooth_box)
                if iou > best_iou and iou >= IOU_THRESHOLD:
                    best_iou = iou
                    best_fdi = fdi

            if best_fdi is None:
                continue

            attr_list = tooth_attributes[best_fdi]
            existing = None
            for item in attr_list:
                if item.get("Value") == attr_name:
                    existing = item
                    break

            description = ATTRIBUTE_DESCRIPTION_MAP.get(attr_name, attr_name)

            if existing is None:
                attr_list.append({
                    "Value": attr_name,
                    "Description": description,
                    "Confidence": attr_conf,
                })
            else:
                if attr_conf > existing.get("Confidence", 0.0):
                    existing["Confidence"] = attr_conf

        teeth_with_attrs = sum(1 for v in tooth_attributes.values() if v)
        logger.info(f"[_analyze_teeth_and_attributes] total teeth with attributes={teeth_with_attrs}")

        # 打印绑定结果
        if tooth_attributes:
            logger.info(f"[DEBUG] 属性绑定结果:")
            for fdi, attrs in tooth_attributes.items():
                logger.info(f"  {fdi}: {[a['Value'] for a in attrs]}")

        # ------------------------------------------------------------------
        # 4. 缺失牙分析
        # ------------------------------------------------------------------
        detected_fdi_set = set(str(fdi) for fdi in tooth_bboxes.keys())
        all_permanent_set = set(ALL_PERMANENT_TEETH_FDI)
        missing_fdi_set = all_permanent_set - detected_fdi_set

        missing_teeth_struct = []
        for fdi in sorted(missing_fdi_set, key=lambda x: int(x)):
            missing_teeth_struct.append({
                "FDI": fdi,
                "Reason": "missing",
                "Detail": f"{fdi}牙位缺牙",
            })

        # ------------------------------------------------------------------
        # 5. 智齿状态分析
        # ------------------------------------------------------------------
        third_molar_summary = {}
        for fdi in WISDOM_TEETH_FDI:
            if fdi not in detected_fdi_set:
                third_molar_summary[fdi] = {
                    "Level": 4,
                    "Impactions": None,
                    "Detail": "未见智齿",
                }
                continue

            attrs = tooth_attributes.get(fdi, [])
            attr_values = {a.get("Value") for a in attrs}

            if "wisdom_tooth_impaction" in attr_values:
                third_molar_summary[fdi] = {
                    "Level": 1,
                    "Impactions": "Impacted",
                    "Detail": "阻生",
                }
            elif "tooth_germ" in attr_values:
                third_molar_summary[fdi] = {
                    "Level": 2,
                    "Impactions": None,
                    "Detail": "牙胚状态（未形成牙根）",
                }
            elif "to_be_erupted" in attr_values or "erupted" in attr_values:
                third_molar_summary[fdi] = {
                    "Level": 3,
                    "Impactions": None,
                    "Detail": "待萌出（垂直生长，无阻碍）",
                }
            else:
                third_molar_summary[fdi] = {
                    "Level": 3,
                    "Impactions": None,
                    "Detail": "已萌出",
                }

        logger.info("=" * 60)
        logger.info("[DEBUG] _analyze_teeth_and_attributes 结束")
        logger.info("=" * 60)

        return {
            "MissingTeeth": missing_teeth_struct,
            "ThirdMolarSummary": third_molar_summary,
            "ToothAttributes": dict(tooth_attributes),
        }

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
        }

        return inference_results
