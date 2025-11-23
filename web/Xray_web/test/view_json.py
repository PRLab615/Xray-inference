#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
快速查看 JSON 文件的脚本
"""

import json
import sys
from pathlib import Path

JSON_FILE = "test_ceph_output.json"

def view_json():
    json_path = Path(JSON_FILE)
    
    if not json_path.exists():
        print(f"错误: 文件 {JSON_FILE} 不存在")
        print("")
        print("请先运行测试脚本生成 JSON 文件:")
        print("  python test_ceph_json.py <taskId>")
        return 1
    
    print("=" * 80)
    print(f"查看 JSON 文件: {JSON_FILE}")
    print("=" * 80)
    print("")
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 显示 CephalometricMeasurements 部分
        if 'data' in data and 'CephalometricMeasurements' in data['data']:
            print("CephalometricMeasurements 部分:")
            print("-" * 80)
            print(json.dumps(
                {'CephalometricMeasurements': data['data']['CephalometricMeasurements']},
                ensure_ascii=False,
                indent=2
            ))
            print("")
            print("-" * 80)
            print("提示: 查看完整 JSON 文件:")
            print(f"  cat {JSON_FILE}")
            print(f"  或")
            print(f"  python -m json.tool {JSON_FILE}")
        else:
            print("完整 JSON 内容:")
            print("-" * 80)
            print(json.dumps(data, ensure_ascii=False, indent=2))
        
        return 0
        
    except json.JSONDecodeError as e:
        print(f"错误: JSON 文件格式错误: {e}")
        return 1
    except Exception as e:
        print(f"错误: 读取文件失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(view_json())

