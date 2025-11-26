# -*- coding: utf-8 -*-
"""
诊断脚本：检查侧位片 Level 值问题
用于找出为什么所有 Level 值都是 1
"""

import json
import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipelines.ceph.ceph_pipeline import CephPipeline
from pipelines.ceph.utils.ceph_report import calculate_measurements
from pipelines.ceph.utils.ceph_report_json import generate_standard_output, _get_measurement_level


def test_pipeline_output():
    """测试 Pipeline 输出的数据"""
    print("=" * 80)
    print("测试 1: 检查 Pipeline 输出的 conclusion 值")
    print("=" * 80)
    
    # 模拟测量数据（使用实际测试值）
    test_measurements = {
        "ANB_Angle": {
            "value": -2.99,
            "unit": "degrees",
            "conclusion": None,  # 这里应该是从 _get_skeletal_class 返回的
            "status": "ok",
        },
        "FH_MP_Angle": {
            "value": 29.83,
            "unit": "degrees",
            "conclusion": None,
            "status": "ok",
        },
        "SGo_NMe_Ratio-1": {
            "value": 66.37,
            "unit": "%",
            "conclusion": None,
            "status": "ok",
        }
    }
    
    # 手动调用函数计算 conclusion
    from pipelines.ceph.utils.ceph_report import (
        _get_skeletal_class,
        _get_growth_type,
        _get_growth_pattern
    )
    
    test_measurements["ANB_Angle"]["conclusion"] = _get_skeletal_class(-2.99)
    test_measurements["FH_MP_Angle"]["conclusion"] = _get_growth_type(29.83)
    test_measurements["SGo_NMe_Ratio-1"]["conclusion"] = _get_growth_pattern(66.37)
    
    print("\n测量项的 conclusion 值:")
    for name, payload in test_measurements.items():
        conclusion = payload.get("conclusion")
        value = payload.get("value")
        print(f"  {name:25s}: conclusion={conclusion} (type={type(conclusion).__name__}), value={value}")
    
    # 测试 _get_measurement_level
    print("\n" + "-" * 80)
    print("测试 2: 检查 _get_measurement_level 函数")
    print("-" * 80)
    
    for name, payload in test_measurements.items():
        conclusion = payload.get("conclusion")
        value = payload.get("value")
        level = _get_measurement_level(name, conclusion, value)
        print(f"  {name:25s}: conclusion={conclusion}, value={value:.2f} → Level={level}")
    
    # 测试完整的 JSON 生成
    print("\n" + "-" * 80)
    print("测试 3: 检查完整的 JSON 生成")
    print("-" * 80)
    
    patient_info = {
        "gender": "Female",
        "DentalAgeStage": "Permanent"
    }
    
    inference_results = {
        "landmarks": {
            "coordinates": {},
            "confidences": {}
        },
        "measurements": test_measurements
    }
    
    result = generate_standard_output(inference_results, patient_info)
    
    measurements = result.get("CephalometricMeasurements", {}).get("AllMeasurements", [])
    print("\n生成的 JSON 中的 Level 值:")
    for m in measurements:
        label = m.get("Label", "N/A")
        level = m.get("Level", "N/A")
        if "Angle" in m:
            value = m.get("Angle")
            print(f"  {label:25s}: Level={level}, Angle={value:.2f}°")
        elif "Ratio" in m:
            value = m.get("Ratio")
            print(f"  {label:25s}: Level={level}, Ratio={value:.2f}%")
    
    # 保存测试结果
    output_file = Path(__file__).parent / "debug_output.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✓ 测试结果已保存到: {output_file}")


if __name__ == "__main__":
    test_pipeline_output()

