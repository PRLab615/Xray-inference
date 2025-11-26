# -*- coding: utf-8 -*-
"""Cephalometric pipeline implementation that conforms to BasePipeline."""

from __future__ import annotations

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
from pipelines.ceph.utils.ceph_report_json import generate_standard_output  # type: ignore


DEFAULT_PATIENT_INFO = {
    "gender": "Female",
    "DentalAgeStage": "Permanent",
}
DEFAULT_IMAGE_PATH = r"D:\git-615\Teeth\Cepath\150_fig\151.jpg"
DEFAULT_OUTPUT_NAME = "ceph_output.json"


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
        for module_name, module_cfg in modules_config.items():
            if not isinstance(module_cfg, dict):
                self.logger.warning(f"Invalid config for module '{module_name}', skipping")
                continue
            
            # 根据模块名称初始化对应的模块
            try:
                if module_name == 'point':
                    self.modules['point'] = self._init_point_module(module_cfg)
                    self.logger.info(f"Successfully initialized module 'point'")
                elif module_name == 'seg':
                    # TODO: 实现 seg 模块初始化
                    self.logger.warning(f"Module 'seg' not implemented yet, skipping")
                else:
                    self.logger.warning(f"Unknown module '{module_name}', skipping")
            except Exception as e:
                self.logger.error(f"Failed to initialize module '{module_name}': {e}", exc_info=True)
                raise
        
        # 检查是否至少初始化了一个模块
        if not self.modules:
            raise ValueError("No modules were successfully initialized for CephPipeline")
        
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

    def run(
        self,
        image_path: str,
        patient_info: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        执行侧位片推理流程
        
        Args:
            image_path: 图像文件路径
            patient_info: 患者信息（必需）
            **kwargs: 其他参数
            
        Returns:
            dict: 符合规范的完整 data 字段
        """
        patient_info = patient_info or kwargs.get("patient_info")
        if not patient_info:
            raise ValueError("patient_info is required for CephPipeline.run")

        self._log_step("开始侧位片推理", f"image_path={image_path}")
        self._load_image(image_path)

        # 使用 point 模块执行推理
        # 如果未来有多个模块，可以在这里协调它们的输出
        if 'point' not in self.modules:
            raise RuntimeError("Point module not initialized, cannot run inference")
        
        point_engine = self.modules['point']
        inference_results = point_engine.run(image_path=image_path, patient_info=patient_info)
        
        result = generate_standard_output(inference_results, patient_info)
        self._log_step("侧位片推理完成", f"keys={list(result.keys())}")
        return result


if __name__ == "__main__":
    pipeline = CephPipeline()
    patient = DEFAULT_PATIENT_INFO

    if not os.path.exists(DEFAULT_IMAGE_PATH):
        raise FileNotFoundError(
            f"请修改 DEFAULT_IMAGE_PATH 为实际存在的图片路径，当前值: {DEFAULT_IMAGE_PATH}"
        )

    data = pipeline.run(DEFAULT_IMAGE_PATH, patient_info=patient)

    output_path = Path(__file__).with_name(DEFAULT_OUTPUT_NAME)
    with output_path.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)

    print(f"Ceph inference finished. JSON saved to: {output_path}")

