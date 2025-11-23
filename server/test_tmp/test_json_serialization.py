# -*- coding: utf-8 -*-
"""
测试 JSON 序列化/反序列化对 Level 值的影响
"""

import json
import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# 模拟正确的数据（从 Pipeline 输出）
correct_data = {
    "CephalometricMeasurements": {
        "AllMeasurements": [
            {
                "Label": "ANB_Angle",
                "Angle": -2.99,
                "Level": 2,  # 正确的值
                "Confidence": 0.0
            },
            {
                "Label": "FH_MP_Angle",
                "Angle": 29.83,
                "Level": 0,  # 正确的值
                "Confidence": 0.0
            },
            {
                "Label": "SGo_NMe_Ratio-1",
                "Ratio": 66.37,
                "Level": 0,  # 正确的值
                "Confidence": 0.0
            }
        ]
    }
}

print("=" * 80)
print("测试 JSON 序列化/反序列化")
print("=" * 80)

# 测试 1: 基本序列化
print("\n1. 基本 JSON 序列化/反序列化:")
serialized = json.dumps(correct_data, ensure_ascii=False)
print(f"   序列化成功，长度: {len(serialized)}")

deserialized = json.loads(serialized)
measurements = deserialized['CephalometricMeasurements']['AllMeasurements']
print("   反序列化后的 Level 值:")
for m in measurements:
    label = m.get('Label', 'N/A')
    level = m.get('Level', 'N/A')
    level_type = type(level).__name__
    print(f"     {label}: Level={level} (type={level_type})")

# 测试 2: 模拟 CallbackManager 发送
print("\n2. 模拟 CallbackManager 发送 (requests.post json=):")
import requests
from unittest.mock import patch

# 模拟 payload
payload = {
    "taskId": "test-123",
    "status": "SUCCESS",
    "data": correct_data
}

# 检查序列化
try:
    serialized_payload = json.dumps(payload, ensure_ascii=False)
    print(f"   Payload 序列化成功，长度: {len(serialized_payload)}")
    
    deserialized_payload = json.loads(serialized_payload)
    measurements = deserialized_payload['data']['CephalometricMeasurements']['AllMeasurements']
    print("   反序列化后的 Level 值:")
    for m in measurements:
        label = m.get('Label', 'N/A')
        level = m.get('Level', 'N/A')
        level_type = type(level).__name__
        print(f"     {label}: Level={level} (type={level_type})")
except Exception as e:
    print(f"   错误: {e}")

# 测试 3: 检查是否有布尔值问题
print("\n3. 测试布尔值转换:")
test_cases = [
    (True, "布尔值 True"),
    (False, "布尔值 False"),
    (1, "整数 1"),
    (0, "整数 0"),
    (2, "整数 2"),
]

for value, desc in test_cases:
    int_value = int(value)
    print(f"   {desc}: {value} → int() = {int_value}")

# 测试 4: 检查 numpy 类型
print("\n4. 测试 numpy 类型:")
try:
    import numpy as np
    
    numpy_int64 = np.int64(2)
    numpy_int32 = np.int32(0)
    
    print(f"   numpy.int64(2): {numpy_int64}, type={type(numpy_int64).__name__}")
    print(f"   numpy.int32(0): {numpy_int32}, type={type(numpy_int32).__name__}")
    
    # JSON 序列化测试
    test_data = {"level": numpy_int64}
    serialized = json.dumps(test_data)
    deserialized = json.loads(serialized)
    print(f"   JSON 序列化后: {deserialized}, type={type(deserialized['level']).__name__}")
    
except ImportError:
    print("   numpy 未安装，跳过测试")

print("\n" + "=" * 80)
print("测试完成")
print("=" * 80)

