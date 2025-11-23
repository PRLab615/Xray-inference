# -*- coding: utf-8 -*-
"""
测试脚本：检查侧位片 JSON 数据流
用于诊断 Level 值不正确的问题
"""

import json
import requests
import sys
from pathlib import Path

# 配置
FLASK_URL = "http://localhost:5000"
TEST_TASK_ID = None  # 如果为 None，将从命令行参数获取

# 注意：由于 Flask 后端使用内存存储，无法直接列出所有 taskId
# 需要从以下方式获取：
# 1. Flask 服务器日志中的 "收到回调" 消息
# 2. 浏览器控制台: appState.currentTaskId
# 3. 前端网络请求中的 taskId


def test_get_result(task_id: str):
    """测试从 Flask 后端获取结果"""
    print("=" * 80)
    print(f"测试：从 Flask 后端获取任务结果 (taskId={task_id})")
    print("=" * 80)
    
    url = f"{FLASK_URL}/get-result?taskId={task_id}"
    print(f"请求 URL: {url}")
    
    try:
        response = requests.get(url, timeout=10)
        print(f"响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print("\n✓ 成功获取结果")
            
            # 检查数据结构
            if 'data' in data:
                ceph_data = data['data']
                
                # 检查 CephalometricMeasurements
                if 'CephalometricMeasurements' in ceph_data:
                    measurements = ceph_data['CephalometricMeasurements'].get('AllMeasurements', [])
                    print(f"\n找到 {len(measurements)} 个测量项")
                    
                    print("\n" + "-" * 80)
                    print("测量项 Level 值详情:")
                    print("-" * 80)
                    
                    for m in measurements:
                        label = m.get('Label', 'N/A')
                        level = m.get('Level', 'N/A')
                        level_type = type(level).__name__
                        
                        if 'Angle' in m:
                            value = m.get('Angle')
                            print(f"  {label:25s}: Level={level} (type={level_type}), Angle={value:.2f}°")
                        elif 'Ratio' in m:
                            value = m.get('Ratio')
                            print(f"  {label:25s}: Level={level} (type={level_type}), Ratio={value:.2f}%")
                        else:
                            print(f"  {label:25s}: Level={level} (type={level_type})")
                    
                    # 验证 Level 值是否正确
                    print("\n" + "-" * 80)
                    print("Level 值验证:")
                    print("-" * 80)
                    
                    for m in measurements:
                        label = m.get('Label', '')
                        level = m.get('Level')
                        expected_level = None
                        actual_value = None
                        
                        if label == 'ANB_Angle':
                            actual_value = m.get('Angle')
                            if actual_value is not None:
                                if actual_value > 6.0:
                                    expected_level = 1  # 骨性II类
                                elif actual_value < 2.0:
                                    expected_level = 2  # 骨性III类
                                else:
                                    expected_level = 0  # 骨性I类
                        elif label == 'FH_MP_Angle':
                            actual_value = m.get('Angle')
                            if actual_value is not None:
                                if actual_value > 33.0:
                                    expected_level = 1  # 高角
                                elif actual_value < 25.0:
                                    expected_level = 2  # 低角
                                else:
                                    expected_level = 0  # 均角
                        elif label.startswith('SGo_NMe_Ratio'):
                            actual_value = m.get('Ratio')
                            if actual_value is not None:
                                if actual_value > 71.0:
                                    expected_level = 1  # 水平生长型
                                elif actual_value < 63.0:
                                    expected_level = 2  # 垂直生长型
                                else:
                                    expected_level = 0  # 平均生长型
                        
                        if expected_level is not None:
                            status = "✓" if level == expected_level else "✗"
                            print(f"  {status} {label:25s}: 期望 Level={expected_level}, 实际 Level={level}, 值={actual_value:.2f}")
                        else:
                            print(f"  ? {label:25s}: Level={level} (无法验证)")
                    
                    # 保存完整 JSON 到文件
                    output_file = Path(__file__).parent / "test_ceph_output.json"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    print(f"\n✓ 完整 JSON 已保存到: {output_file}")
                    print(f"   查看文件: cat {output_file}")
                    print(f"   或使用: less {output_file}")
                    
                    # 打印 CephalometricMeasurements 部分
                    print("\n" + "=" * 80)
                    print("CephalometricMeasurements 部分 JSON:")
                    print("=" * 80)
                    print(json.dumps(
                        {'CephalometricMeasurements': ceph_data['CephalometricMeasurements']},
                        ensure_ascii=False,
                        indent=2
                    ))
                else:
                    print("\n✗ 未找到 CephalometricMeasurements 字段")
                    print("可用字段:", list(ceph_data.keys()))
            else:
                print("\n✗ 响应中没有 'data' 字段")
                print("响应内容:", json.dumps(data, ensure_ascii=False, indent=2))
        elif response.status_code == 404:
            print("\n✗ 结果未找到 (404)")
            print("可能原因:")
            print("  1. taskId 不正确")
            print("  2. 任务尚未完成")
            print("  3. Flask 后端未收到回调")
        else:
            print(f"\n✗ 请求失败，状态码: {response.status_code}")
            print("响应内容:", response.text)
            
    except requests.exceptions.RequestException as e:
        print(f"\n✗ 请求失败: {e}")
        print("\n请确保:")
        print("  1. Flask 服务器正在运行 (http://localhost:5000)")
        print("  2. 网络连接正常")


def test_health():
    """测试 Flask 后端健康状态"""
    print("=" * 80)
    print("测试：Flask 后端健康检查")
    print("=" * 80)
    
    try:
        response = requests.get(f"{FLASK_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✓ Flask 后端运行正常")
            return True
        else:
            print(f"✗ Flask 后端响应异常，状态码: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"✗ 无法连接到 Flask 后端: {e}")
        print(f"  请确保 Flask 服务器运行在: {FLASK_URL}")
        return False


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("侧位片 JSON 数据流测试脚本")
    print("=" * 80)
    
    # 健康检查
    if not test_health():
        print("\n请先启动 Flask 服务器:")
        print("  cd web/Xray_web")
        print("  python app.py")
        sys.exit(1)
    
    # 获取 taskId
    task_id = TEST_TASK_ID
    if not task_id:
        if len(sys.argv) > 1:
            task_id = sys.argv[1]
        else:
            print("\n" + "=" * 80)
            print("使用方法:")
            print("=" * 80)
            print("\n1. 基本用法（需要 taskId）:")
            print("   python test_ceph_json.py <taskId>")
            print("\n2. 如何获取 taskId:")
            print("   方法 A: 查看 Flask 服务器日志")
            print("         查找 '收到回调: taskId=xxx' 消息")
            print("\n   方法 B: 在浏览器控制台执行")
            print("          console.log(appState.currentTaskId)")
            print("\n   方法 C: 查看浏览器网络请求")
            print("          在 Network 标签中找到 /get-result?taskId=xxx")
            print("\n3. 查看输出的 JSON:")
            print("   - 脚本会在控制台打印 CephalometricMeasurements 部分")
            print("   - 完整 JSON 会保存到: test_ceph_output.json")
            print("   - 使用以下命令查看文件:")
            print("     cat test_ceph_output.json")
            print("     或")
            print("     less test_ceph_output.json")
            print("\n" + "=" * 80)
            sys.exit(1)
    
    # 测试获取结果
    test_get_result(task_id)
    
    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)

