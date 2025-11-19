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


# DEFAULT_PATIENT_INFO = {
#     "gender": "Female",
#     "DentalAgeStage": "Permanent",
# }
# DEFAULT_IMAGE_PATH = r"D:\git-615\Teeth\Cepath\150_fig\152.jpg"
# DEFAULT_OUTPUT_NAME = "ceph_output.json"


class CephPipeline(BasePipeline):
    """侧位片推理管道，实现 BasePipeline 的 run() 接口。"""

    def __init__(
        self,
        *,
        weights_path: Optional[str] = None,
        weights_key: Optional[str] = None,
        weights_force_download: bool = False,
        device: str = "0",
        image_size: int = 1024,
        conf: float = 0.25,
        iou: float = 0.6,
        max_det: int = 1,
    ):
        super().__init__()
        self.pipeline_type = "cephalometric"
        self.engine = CephInferenceEngine(
            weights_path=weights_path,
            weights_key=weights_key,
            weights_force_download=weights_force_download,
            device=device,
            image_size=image_size,
            conf=conf,
            iou=iou,
            max_det=max_det,
        )

    def run(
        self,
        image_path: str,
        patient_info: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """继承自 BasePipeline 的统一入口。"""
        patient_info = patient_info or kwargs.get("patient_info")
        if not patient_info:
            raise ValueError("patient_info is required for CephPipeline.run")

        self._log_step("开始侧位片推理", f"image_path={image_path}")
        self._load_image(image_path)

        inference_results = self.engine.run(image_path=image_path, patient_info=patient_info)
        result = generate_standard_output(inference_results, patient_info)
        self._log_step("侧位片推理完成", f"keys={list(result.keys())}")
        return result


# if __name__ == "__main__":
#     pipeline = CephPipeline()
#     patient = DEFAULT_PATIENT_INFO

#     if not os.path.exists(DEFAULT_IMAGE_PATH):
#         raise FileNotFoundError(
#             f"请修改 DEFAULT_IMAGE_PATH 为实际存在的图片路径，当前值: {DEFAULT_IMAGE_PATH}"
#         )

#     data = pipeline.run(DEFAULT_IMAGE_PATH, patient_info=patient)

#     output_path = Path(__file__).with_name(DEFAULT_OUTPUT_NAME)
#     with output_path.open("w", encoding="utf-8") as fp:
#         json.dump(data, fp, ensure_ascii=False, indent=2)

#     print(f"Ceph inference finished. JSON saved to: {output_path}")

