"""
Flask 服务器功能测试脚本
用于验证步骤1和步骤2的所有接口
"""
import urllib.request
import urllib.error
import json
import time

def test_health():
    """测试健康检查接口"""
    print("\n[测试1] 健康检查接口 GET /health")
    try:
        response = urllib.request.urlopen('http://localhost:5000/health')
        data = json.loads(response.read().decode())
        print(f"✓ 返回: {data}")
        assert data['status'] == 'ok', "状态不正确"
        print("✓ 测试通过")
        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False


def test_index():
    """测试主页面"""
    print("\n[测试2] 主页面 GET /")
    try:
        response = urllib.request.urlopen('http://localhost:5000/')
        html = response.read().decode()
        print(f"✓ 返回 HTML 长度: {len(html)} 字符")
        assert 'AI 异步分析测试平台' in html, "页面内容不正确"
        print("✓ 测试通过")
        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False


def test_callback():
    """测试回调接收接口"""
    print("\n[测试3] 回调接收接口 POST /callback")
    try:
        # 准备测试数据
        test_data = {
            "taskId": "test-task-123",
            "status": "SUCCESS",
            "timestamp": "2025-11-17T10:00:00Z",
            "data": {"result": "测试成功"}
        }
        
        # 发送 POST 请求
        req = urllib.request.Request(
            'http://localhost:5000/callback',
            data=json.dumps(test_data).encode(),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        response = urllib.request.urlopen(req)
        result = json.loads(response.read().decode())
        
        print(f"✓ 返回: {result}")
        assert result['status'] == 'received', "状态不正确"
        print("✓ 测试通过")
        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False


def test_get_result_found():
    """测试结果查询接口 - 结果存在"""
    print("\n[测试4] 结果查询接口 GET /get-result (结果存在)")
    try:
        response = urllib.request.urlopen('http://localhost:5000/get-result?taskId=test-task-123')
        data = json.loads(response.read().decode())
        
        print(f"✓ 返回: {json.dumps(data, ensure_ascii=False)}")
        assert data['taskId'] == 'test-task-123', "taskId 不匹配"
        assert data['status'] == 'SUCCESS', "status 不正确"
        print("✓ 测试通过")
        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False


def test_get_result_not_found():
    """测试结果查询接口 - 结果不存在"""
    print("\n[测试5] 结果查询接口 GET /get-result (结果不存在)")
    try:
        response = urllib.request.urlopen('http://localhost:5000/get-result?taskId=non-existent-task')
    except urllib.error.HTTPError as e:
        if e.code == 404:
            data = json.loads(e.read().decode())
            print(f"✓ 返回 404: {data}")
            assert data['status'] == 'pending', "状态不正确"
            print("✓ 测试通过")
            return True
        else:
            print(f"✗ 预期 404，实际返回 {e.code}")
            return False
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False


def test_callback_missing_taskid():
    """测试回调接收接口 - 缺少 taskId"""
    print("\n[测试6] 回调接收接口 POST /callback (缺少 taskId)")
    try:
        test_data = {"status": "SUCCESS"}
        req = urllib.request.Request(
            'http://localhost:5000/callback',
            data=json.dumps(test_data).encode(),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        response = urllib.request.urlopen(req)
        print(f"✗ 预期返回 400，实际返回 {response.code}")
        return False
    except urllib.error.HTTPError as e:
        if e.code == 400:
            data = json.loads(e.read().decode())
            print(f"✓ 返回 400: {data}")
            assert 'error' in data, "错误信息不存在"
            print("✓ 测试通过")
            return True
        else:
            print(f"✗ 预期 400，实际返回 {e.code}")
            return False


def main():
    print("=" * 60)
    print("Flask 服务器功能测试")
    print("=" * 60)
    
    # 等待服务器启动
    print("\n等待服务器启动...")
    time.sleep(2)
    
    # 执行所有测试
    results = []
    results.append(("健康检查接口", test_health()))
    results.append(("主页面", test_index()))
    results.append(("回调接收接口 (正常)", test_callback()))
    results.append(("结果查询接口 (存在)", test_get_result_found()))
    results.append(("结果查询接口 (不存在)", test_get_result_not_found()))
    results.append(("回调接收接口 (异常)", test_callback_missing_taskid()))
    
    # 统计结果
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{status} - {name}")
    
    print(f"\n总计: {passed}/{total} 通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！步骤1和步骤2实现完成。")
    else:
        print("\n⚠️ 部分测试失败，请检查服务器状态。")


if __name__ == '__main__':
    main()

