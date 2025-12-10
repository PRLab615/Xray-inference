# -*- coding: utf-8 -*-
"""Cephalometric pipeline implementation that conforms to BasePipeline."""
import pprint
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from pipelines.base_pipeline import BasePipeline  # type: ignore
from pipelines.ceph.modules.point.point_model import CephInferenceEngine  # type: ignore
from pipelines.ceph.modules.point_11.point_11_model import Point11Model  # type: ignore
from pipelines.ceph.modules.CVM.cvm_model import CVMInferenceEngine  # type: ignore
from pipelines.ceph.utils.ceph_report_json import generate_standard_output  # type: ignore
from pipelines.ceph.utils.ceph_report import calculate_airway_measurements, calculate_adenoid_ratio  # type: ignore
from tools.timer import timer


# DEFAULT_PATIENT_INFO = {
#     "gender": "Female",
#     "DentalAgeStage": "Permanent",
# }
# # DEFAULT_IMAGE_PATH = r"D:\git-615\Teeth\Xray-inference\example\example_ceph_img.jpg"
# DEFAULT_IMAGE_PATH = r"/app/example/example_ceph_img.jpg"
# DEFAULT_OUTPUT_NAME = "ceph_output.json"


class CephPipeline(BasePipeline):
    """
    侧位片推理管道，实现 BasePipeline 的 run() 接口。
    
    架构设计（v3.2）：
        - 在初始化时，一次性加载所有 enabled 的模块
        - 支持多模块并存（point, seg, measurement 等）
        - 通过 modules 参数接收配置，不再使用 default_module
    """

    def __init__(self, *, modules: Optional[Dict[str, Dict[str, Any]]] = None):
        """
        初始化侧位片 Pipeline
        
        Args:
            modules: 模块配置字典，格式如下：
                {
                    "point": {
                        "enabled": True,
                        "weights_key": "...",
                        "device": "0",
                        ...
                    },
                    "seg": {
                        "enabled": False,
                        ...
                    }
                }
        """
        super().__init__()
        self.pipeline_type = "cephalometric"
        self.modules = {}  # 存储所有已初始化的模块实例
        
        # 初始化所有 enabled 的模块
        if modules:
            self._initialize_modules(modules)
        else:
            # 兼容旧代码：如果没有传入 modules，使用默认配置
            self.logger.warning("No modules config provided, initializing point module with defaults")
            self.modules['point'] = CephInferenceEngine()
    
    def _initialize_modules(self, modules_config: Dict[str, Dict[str, Any]]):
        """
        遍历所有模块配置，初始化所有配置中声明的模块
        
        Args:
            modules_config: 完整的模块配置字典
            
        设计原则（v3.2）：
            - 配置中存在的模块 = 需要初始化的模块
            - 不需要的模块直接从配置中移除（或注释掉）
            - 不使用 enabled 参数，简化配置逻辑
        """
        from tools.weight_fetcher import WeightFetchError
        
        for module_name, module_cfg in modules_config.items():
            if not isinstance(module_cfg, dict):
                self.logger.warning(f"Invalid config for module '{module_name}', skipping")
                continue
            
            # 根据模块名称初始化对应的模块
            try:
                if module_name == 'point':
                    self.modules['point'] = self._init_point_module(module_cfg)
                    self.logger.info(f"Successfully initialized module 'point'")
                elif module_name == 'point_11':
                    self.modules['point_11'] = self._init_point_11_module(module_cfg)
                    self.logger.info(f"Successfully initialized module 'point_11'")
                elif module_name == 'cvm':
                    self.modules['cvm'] = self._init_cvm_module(module_cfg)
                    self.logger.info(f"Successfully initialized module 'cvm'")
                elif module_name == 'seg':
                    # TODO: 实现 seg 模块初始化
                    self.logger.warning(f"Module 'seg' not implemented yet, skipping")
                else:
                    self.logger.warning(f"Unknown module '{module_name}', skipping")
            except (WeightFetchError, FileNotFoundError) as e:
                # 权重加载失败：本地缓存没有且S3连接失败
                self.logger.error(f"Failed to load model weights for module '{module_name}': {e}")
                self.logger.warning("Entering MOCK MODE: Will return example JSON data for all inference requests")
                self.is_mock_mode = True
                break  # 权重加载失败，停止初始化其他模块
            except Exception as e:
                # 其他初始化错误仍然抛出（不通过错误消息判断，避免误判）
                self.logger.error(f"Failed to initialize module '{module_name}': {e}", exc_info=True)
                raise
        
        # 检查是否至少初始化了一个模块（除非处于mock模式）
        if not self.modules and not self.is_mock_mode:
            raise ValueError("No modules were successfully initialized for CephPipeline")
        
        if self.is_mock_mode:
            self.logger.info("CephPipeline initialized in MOCK MODE")
        else:
            self.logger.info(f"CephPipeline initialized with modules: {list(self.modules.keys())}")
    
    def _init_point_module(self, config: Dict[str, Any]) -> CephInferenceEngine:
        """
        初始化 point 模块（关键点检测）
        
        Args:
            config: point 模块的配置字典
            
        Returns:
            CephInferenceEngine: 初始化好的 point 模块实例
        """
        # 提取配置参数，排除元数据字段（非构造参数）
        exclude_keys = {'description'}
        init_kwargs = {k: v for k, v in config.items() if k not in exclude_keys}
        
        self.logger.info(f"Initializing point module with kwargs: {init_kwargs}")
        return CephInferenceEngine(**init_kwargs)

    def _init_cvm_module(self, config: Dict[str, Any]) -> CVMInferenceEngine:
        """
        初始化 CVM 模块（颈椎成熟度检测）
        
        Args:
            config: CVM 模块的配置字典
            
        Returns:
            CVMInferenceEngine: 初始化好的 CVM 模块实例
        """
        # 提取配置参数，排除元数据字段（非构造参数）
        exclude_keys = {'description'}
        init_kwargs = {k: v for k, v in config.items() if k not in exclude_keys}
        
        self.logger.info(f"Initializing CVM module with kwargs: {init_kwargs}")
        return CVMInferenceEngine(**init_kwargs)

    def _init_point_11_module(self, config: Dict[str, Any]) -> Point11Model:
        """
        初始化 point_11 模块（气道/腺体 11 点位标志点检测）
        
        Args:
            config: point_11 模块的配置字典
            
        Returns:
            Point11Model: 初始化好的 point_11 模块实例
        """
        # 提取配置参数，排除元数据字段（非构造参数）
        exclude_keys = {'description'}
        init_kwargs = {k: v for k, v in config.items() if k not in exclude_keys}
        
        self.logger.info(f"Initializing point_11 module with kwargs: {init_kwargs}")
        return Point11Model(**init_kwargs)

    def run(
        self,
        image_path: str,
        patient_info: Optional[Dict[str, str]] = None,
        pixel_spacing: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        执行侧位片推理流程
        
        Args:
            image_path: 图像文件路径
            patient_info: 患者信息（必需）
            pixel_spacing: 像素间距/比例尺信息（可选）
                - scale_x: 水平方向 1像素 = 多少mm
                - scale_y: 垂直方向 1像素 = 多少mm
                - source: 数据来源（"dicom" 或 "request"）
            **kwargs: 其他参数
            
        Returns:
            dict: 符合规范的完整 data 字段
        """
        # Mock模式：返回示例JSON
        if self.is_mock_mode:
            from server.utils.mock_data_loader import load_example_json
            self.logger.warning("Pipeline is in MOCK MODE, returning example JSON data")
            example_data = load_example_json('cephalometric')
            if example_data:
                # 示例JSON可能包含完整的响应结构，需要提取data字段
                if 'data' in example_data:
                    return example_data['data']
                return example_data
            else:
                self.logger.error("Failed to load example JSON, returning empty dict")
                return {}
        
        # 重置计时器
        timer.reset()
        
        patient_info = patient_info or kwargs.get("patient_info")
        pixel_spacing = pixel_spacing or kwargs.get("pixel_spacing")
        
        if not patient_info:
            raise ValueError("patient_info is required for CephPipeline.run")

        self._log_step("开始侧位片推理", f"image_path={image_path}")
        self._load_image(image_path)

        # ===== 步骤 1: Point 模块推理（25点关键点检测）=====
        # Point 模块是必需的，用于检测头影测量关键点和计算测量值
        if 'point' not in self.modules:
            raise RuntimeError("Point module not initialized, cannot run inference")
        
        self.logger.info("执行 Point 模块推理（25点关键点检测）...")
        point_engine = self.modules['point']
        # 内部已埋点 ceph_point.pre/inference/post/measurement
        inference_results = point_engine.run(
            image_path=image_path, 
            patient_info=patient_info,
            pixel_spacing=pixel_spacing
        )
        self.logger.info("Point 模块推理完成")

        # ===== 步骤 2: Point_11 模块推理（气道/腺体 11 点位检测）=====
        # Point_11 模块是可选的，用于检测气道和腺体相关标志点
        if 'point_11' in self.modules:
            self.logger.info("执行 Point_11 模块推理（气道/腺体 11 点位检测）...")
            point_11_model = self.modules['point_11']
            # 内部已埋点 ceph_point11.pre/inference/post
            point_11_result = point_11_model.predict(image_path=image_path)
            
            # 将 11 点结果合并到 inference_results 中
            point_11_dict = Point11Model.landmark_result_to_dict(point_11_result)
            
            # 合并坐标到 landmarks
            if "landmarks" not in inference_results:
                inference_results["landmarks"] = {}
            if "landmarks_11" not in inference_results:
                inference_results["landmarks_11"] = point_11_dict
            
            # 计算气道测量（需要 25 点和 11 点坐标 + spacing）
            spacing = inference_results.get("spacing", 0.1)
            landmarks_25 = inference_results.get("landmarks", {}).get("coordinates", {})
            landmarks_11 = point_11_dict.get("coordinates", {})
            
            with timer.record("ceph_point11.airway_measurement"):
                airway_result = calculate_airway_measurements(
                    landmarks_25=landmarks_25,
                    landmarks_11=landmarks_11,
                    spacing=spacing
                )
                adenoid_result = calculate_adenoid_ratio(
                    landmarks_25=landmarks_25,
                    landmarks_11=landmarks_11,
                    spacing=spacing
                )
            
            # 确保 measurements 字典存在
            if "measurements" not in inference_results:
                inference_results["measurements"] = {}
            
            # 添加气道和腺体测量项
            inference_results["measurements"]["Airway_Gap"] = airway_result
            inference_results["measurements"]["Adenoid_Index"] = adenoid_result
            
            self.logger.info(
                "Point_11 模块推理完成: %d/11 点位检测成功, 气道测量=%s, 腺样体指数=%.2f",
                len(point_11_result.detected),
                "正常" if airway_result.get("conclusion", False) else "不足",
                adenoid_result.get("value", 0.0)
            )
        else:
            self.logger.info("Point_11 模块未初始化，跳过气道/腺体检测")

        # ===== 步骤 4: CVM 模块推理（颈椎成熟度检测）=====
        # CVM 模块是可选的，如果已初始化则执行推理并合并结果
        if 'cvm' in self.modules:
            self.logger.info("执行 CVM 模块推理（颈椎成熟度检测）...")
            cvm_engine = self.modules['cvm']
            # 内部已埋点 ceph_cvm.pre/inference/post
            cvm_result = cvm_engine.run(image_path=image_path)
            
            # 将 CVM 结果转换为测量项格式并合并到 measurements 中
            cvm_measurement = {
                "coordinates": cvm_result.get("coordinates", []),
                "conclusion": cvm_result.get("level", 0),  # CS阶段 (1-6) 或 0
                "confidence": cvm_result.get("confidence", 0.0),
                "serialized_mask": cvm_result.get("serialized_mask", ""),
            }
            
            # 确保 measurements 字典存在
            if "measurements" not in inference_results:
                inference_results["measurements"] = {}
            
            # 添加 CVM 测量项
            inference_results["measurements"]["Cervical_Vertebral_Maturity_Stage"] = cvm_measurement
            self.logger.info(
                "CVM 模块推理完成，结果已合并到 measurements: level=%d, confidence=%.4f", 
                cvm_result.get("level", 0), 
                cvm_result.get("confidence", 0.0)
            )
        else:
            self.logger.info("CVM 模块未初始化，跳过颈椎成熟度检测")

        #1
        # 注释掉调试打印，避免刷屏
        # print("\n=== [1] Point 模块推理原始输出 (inference_results) ===")
        # pprint.pprint(inference_results, width=120, depth=5)
        # # 如果你只关心关键点坐标和测量值，也可以单独打印：
        # if isinstance(inference_results, dict):
        #     print("\n>>> 关键点坐标 (landmarks):")
        #     pprint.pprint(inference_results.get("landmarks") or inference_results.get("points"), width=120)
        #     print("\n>>> 测量值 (measurements):")
        #     pprint.pprint(inference_results.get("measurements"), width=120)
        # print("=" * 60)


        # ===== 步骤 5: 生成标准 JSON 输出 =====
        # 将推理结果格式化为符合规范的 JSON 格式
        # spacing 已在 inference_results 中
        with timer.record("report.generation"):
            result = generate_standard_output(inference_results, patient_info)



        # 保存计时报告
        timer.print_report()
        timer.save_report()  # 使用配置中的路径



        self._log_step("侧位片推理完成", f"keys={list(result.keys())}")
        return result


# if __name__ == "__main__":
#     # 从 config.yaml 加载配置
#     import yaml
#     from pathlib import Path
#
#     # 加载配置文件
#     config_path = Path(__file__).resolve().parents[2] / "config.yaml"
#     if not config_path.exists():
#         raise FileNotFoundError(f"配置文件不存在: {config_path}")
#
#     with open(config_path, 'r', encoding='utf-8') as f:
#         config = yaml.safe_load(f)
#
#     # 获取侧位片 pipeline 的模块配置
#     cephalometric_config = config.get("pipelines", {}).get("cephalometric", {})
#     modules_config = cephalometric_config.get("modules", {})
#
#     if not modules_config:
#         raise ValueError("config.yaml 中未找到 pipelines.cephalometric.modules 配置")
#
#     print("从 config.yaml 加载的模块配置:")
#     for module_name, module_cfg in modules_config.items():
#         print(f"  - {module_name}: {module_cfg.get('description', 'N/A')}")
#
#     # 初始化 pipeline
#     pipeline = CephPipeline(modules=modules_config)
#     patient = DEFAULT_PATIENT_INFO
#
#     if not os.path.exists(DEFAULT_IMAGE_PATH):
#         raise FileNotFoundError(
#             f"请修改 DEFAULT_IMAGE_PATH 为实际存在的图片路径，当前值: {DEFAULT_IMAGE_PATH}"
#         )
#
#     data = pipeline.run(DEFAULT_IMAGE_PATH, patient_info=patient)
#
#     # 输出 JSON 到指定目录
#     output_dir = Path(r"/app/example/")
#     output_path = output_dir / DEFAULT_OUTPUT_NAME
#     output_dir.mkdir(parents=True, exist_ok=True)
#
#     with output_path.open("w", encoding="utf-8") as fp:
#         json.dump(data, fp, ensure_ascii=False, indent=2)
#
#     print(f"\n✅ Ceph inference finished. JSON saved to: {output_path}")
#
#     # 检查 CVM 结果是否在输出中
#     if "CephalometricMeasurements" in data:
#         measurements = data["CephalometricMeasurements"].get("AllMeasurements", [])
#         cvm_measurement = next(
#             (m for m in measurements if m.get("Label") == "Cervical_Vertebral_Maturity_Stage"),
#             None
#         )
#         if cvm_measurement:
#             print(f"\n✅ CVM 结果已包含在输出中:")
#             print(f"   Level: {cvm_measurement.get('Level')}")
#             print(f"   Confidence: {cvm_measurement.get('Confidence')}")
#             print(f"   Coordinates: {cvm_measurement.get('Coordinates')}")
#         else:
#             print("\n⚠️  CVM 结果未在输出中找到（可能 CVM 模块未初始化或推理失败）")

