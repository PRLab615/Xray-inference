# -*- coding: utf-8 -*-
"""
测试样例：只测试文件上传功能（含回调服务器）
"""

import requests
import json
import uuid
import os
import threading
import time
from flask import Flask, request
from datetime import datetime

# ==================== 配置（支持环境变量覆盖） ====================
API_HOST = os.getenv('API_HOST', 'localhost')
API_PORT = os.getenv('API_PORT', '9010')
API_URL = os.getenv('API_URL', f"http://{API_HOST}:{API_PORT}/api/v1/analyze")

CALLBACK_HOST = os.getenv('CALLBACK_HOST', 'localhost')
CALLBACK_PORT = int(os.getenv('CALLBACK_PORT', '5556'))
CALLBACK_URL = os.getenv('CALLBACK_URL', f"http://{CALLBACK_HOST}:{CALLBACK_PORT}/callback")

TEST_IMAGE_PATH = os.getenv('TEST_IMAGE_PATH', "./test_image.jpg")
# ============================================

# ==================== 回调服务器 ====================
callback_received = threading.Event()
callback_data = None

app = Flask(__name__)


@app.route('/callback', methods=['POST'])
def callback():
    """接收 API 回调"""
    global callback_data

    print(f"\n{'=' * 70}")
    print(f"📥 收到回调！")
    print(f"{'=' * 70}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"请求头:")
    for key, value in request.headers.items():
        print(f"  {key}: {value}")

    try:
        callback_data = request.json
        print(f"\n回调内容:")
        print(json.dumps(callback_data, indent=2, ensure_ascii=False))

        # 检查字段
        status = callback_data.get('status', 'UNKNOWN')
        print(f"\n任务状态: {status}")

        if status == "SUCCESS":
            print(f"✅ 任务成功完成！")
        elif status == "FAILED":
            print(f"❌ 任务失败")
            error = callback_data.get('error', {})
            print(f"错误信息: {error.get('message', 'N/A')}")

        callback_received.set()
        return {"message": "Callback received"}, 200

    except Exception as e:
        print(f"❌ 解析回调失败: {e}")
        return {"error": str(e)}, 400


def run_callback_server():
    """在独立线程中运行回调服务器"""
    # 禁用 Flask 和 Werkzeug 的日志输出
    import logging as flask_logging
    log = flask_logging.getLogger('werkzeug')
    log.setLevel(flask_logging.ERROR)

    app.run(host='0.0.0.0', port=CALLBACK_PORT, debug=False, use_reloader=False)


# ============================================

print("=" * 70)
print("文件上传测试（含回调服务器）")
print("=" * 70)

# 启动回调服务器
print(f"\n[步骤0] 启动本地回调服务器...")
print(f"回调地址: {CALLBACK_URL}")
print(f"监听端口: {CALLBACK_PORT}")

server_thread = threading.Thread(target=run_callback_server, daemon=True)
server_thread.start()
time.sleep(2)  # 等待服务器启动
print(f"✅ 回调服务器已启动")

# 1. 检查图片是否存在
print(f"\n[步骤1] 检查图片文件...")
print(f"路径: {TEST_IMAGE_PATH}")

if os.path.exists(TEST_IMAGE_PATH):
    file_size = os.path.getsize(TEST_IMAGE_PATH)
    print(f"✅ 文件存在，大小: {file_size / 1024:.2f} KB")
else:
    print(f"❌ 文件不存在！")
    exit(1)

# 2. 生成 taskId
task_id = str(uuid.uuid4())
print(f"\n[步骤2] 生成 taskId...")
print(f"taskId: {task_id}")

# 3. 准备请求数据
print(f"\n[步骤3] 准备请求数据...")

files = {
    'image': open(TEST_IMAGE_PATH, 'rb')
}

data = {
    'taskId': task_id,
    'taskType': 'panoramic',
    'callbackUrl': CALLBACK_URL,
    'metadata': json.dumps({
        "patientId": "P-TEST-001",
        "orderId": "O-TEST-001",
        "test": "file_upload_debug"
    })
}

print(f"API URL: {API_URL}")
print(f"文件: {TEST_IMAGE_PATH}")
print(f"taskType: {data['taskType']}")
print(f"callbackUrl: {data['callbackUrl']}")
print(f"metadata: {data['metadata']}")

# 4. 发送请求
print(f"\n[步骤4] 发送 POST 请求...")
print(f"请稍等...")

try:
    response = requests.post(
        API_URL,
        files=files,
        data=data,
        timeout=30
    )

    print(f"\n[步骤5] 收到响应...")
    print(f"=" * 70)
    print(f"Status Code: {response.status_code}")
    print(f"Response Headers:")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")

    print(f"\nResponse Body:")
    print(response.text)

    # 尝试解析 JSON
    try:
        resp_json = response.json()
        print(f"\nJSON 格式化:")
        print(json.dumps(resp_json, indent=2, ensure_ascii=False))
    except:
        print(f"\n(无法解析为 JSON)")

    print(f"=" * 70)

    # 判断成功或失败
    if response.status_code == 202:
        print(f"\n✅ 请求已接受！任务已入队")

        # 等待回调
        print(f"\n[步骤6] 等待回调...")
        print(f"等待最多 60 秒...")

        if callback_received.wait(timeout=60):
            print(f"\n✅ 已收到回调（详见上方）")
        else:
            print(f"\n⚠️  等待超时，未收到回调")
            print(f"\n可能原因:")
            print(f"  1. Worker 未启动或处理任务失败")
            print(f"  2. 回调 URL 不可达（检查 Docker 网络）")
            print(f"  3. 任务处理时间过长")
            print(f"\n排查步骤:")
            print(f"  1. 查看 Worker 日志: docker logs xray_worker")
            print(f"  2. 查看 API 日志: docker logs xray_api")
            print(f"  3. 确认回调 URL 可达: {CALLBACK_URL}")

    elif response.status_code == 400:
        print(f"\n❌ 请求参数错误 (400)")
        print(f"请检查参数格式")
    elif response.status_code == 409:
        print(f"\n❌ taskId 已存在 (409)")
        print(f"taskId: {task_id}")
    elif response.status_code == 500:
        print(f"\n❌ 服务器内部错误 (500)")
        print(f"请检查 API 服务日志")
    else:
        print(f"\n❌ 未预期的状态码: {response.status_code}")

except requests.exceptions.ConnectionError as e:
    print(f"\n❌ 连接失败!")
    print(f"错误: {e}")
    print(f"\n可能原因:")
    print(f"  1. API 服务未启动")
    print(f"  2. API URL 不正确: {API_URL}")
    print(f"  3. 网络不通")
    print(f"\n排查步骤:")
    print(f"  1. 确认服务器上 API 是否运行: docker ps | grep xray_api")
    print(f"  2. 确认端口是否对外开放: telnet {API_HOST} {API_PORT}")
    print(f"  3. 尝试访问健康检查: curl http://{API_HOST}:{API_PORT}/health")

except requests.exceptions.Timeout as e:
    print(f"\n❌ 请求超时!")
    print(f"错误: {e}")
    print(f"\n可能原因:")
    print(f"  1. 服务器处理太慢")
    print(f"  2. 网络延迟过高")

except Exception as e:
    print(f"\n❌ 发生错误!")
    print(f"错误类型: {type(e).__name__}")
    print(f"错误信息: {e}")

    import traceback

    print(f"\n完整堆栈:")
    traceback.print_exc()

finally:
    files['image'].close()
    print(f"\n文件已关闭")

# 测试总结
print(f"\n" + "=" * 70)
print(f"测试总结")
print(f"=" * 70)
print(f"任务 ID: {task_id}")
print(f"回调接收: {'✅ 成功' if callback_received.is_set() else '❌ 未收到'}")
if callback_data:
    print(f"任务状态: {callback_data.get('status', 'UNKNOWN')}")
print(f"\n提示:")
print(f"  - 如果未收到回调，请检查:")
print(f"    1. Worker 日志: docker logs xray_worker")
print(f"    2. API 日志: docker logs xray_api")
print(f"    3. 回调 URL 是否可达: {CALLBACK_URL}")
print(f"=" * 70)

