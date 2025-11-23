# -*- coding: utf-8 -*-
"""
Flask 微型回调服务器
提供三个核心功能：
1. 静态文件服务：为前端页面提供 HTTP 访问
2. 回调接收接口：接收 AI 后端的异步回调
3. 结果查询接口：供前端轮询查询任务结果
"""
from flask import Flask, send_from_directory, jsonify, request
import os

# 配置 Flask 应用的静态文件路径
app = Flask(__name__, 
            static_folder='static',
            static_url_path='/static')

# 全局内存存储：存储任务结果
task_results = {}


@app.route('/')
def index():
    """
    提供前端主页面的静态文件服务
    返回: static/index.html
    """
    return send_from_directory('static', 'index.html')


@app.route('/static/<path:filename>')
def serve_static(filename):
    """
    提供静态资源文件服务（CSS、JS 等）
    返回: static/ 目录下的文件
    """
    return send_from_directory('static', filename)


@app.route('/health')
def health():
    """
    健康检查接口
    返回: {"status": "ok"}
    """
    return jsonify({"status": "ok"})


@app.route('/callback', methods=['POST'])
def callback():
    """
    接收 AI 后端的异步回调请求，并将结果存储到内存
    
    请求体格式 (JSON):
    {
        "taskId": "string",
        "status": "SUCCESS | FAILURE",
        "timestamp": "ISO 8601 时间戳",
        "data": {...} | null,
        "error": {...} | null
    }
    
    返回:
    - 成功: {"status": "received"} (HTTP 200)
    - 失败: {"error": "Missing taskId"} (HTTP 400)
    """
    data = request.get_json()
    
    if not data or 'taskId' not in data:
        return jsonify({"error": "Missing taskId"}), 400
    
    task_id = data['taskId']
    task_results[task_id] = data
    
    print("收到回调: taskId={}, status={}".format(task_id, data.get('status')))
    
    # 调试：打印 CephalometricMeasurements 的 Level 值
    if data.get('status') == 'SUCCESS' and 'data' in data:
        ceph_data = data.get('data', {})
        if 'CephalometricMeasurements' in ceph_data:
            measurements = ceph_data['CephalometricMeasurements'].get('AllMeasurements', [])
            print("\n[调试] Flask 接收到的 CephalometricMeasurements Level 值:")
            for m in measurements:
                label = m.get('Label', 'N/A')
                level = m.get('Level', 'N/A')
                level_type = type(level).__name__
                if 'Angle' in m:
                    value = m.get('Angle')
                    print("  {}: Level={} (type={}), Angle={}".format(label, level, level_type, value))
                elif 'Ratio' in m:
                    value = m.get('Ratio')
                    print("  {}: Level={} (type={}), Ratio={}".format(label, level, level_type, value))
            
            # 打印原始 JSON 字符串的一部分（用于检查序列化问题）
            import json
            raw_json = json.dumps(ceph_data['CephalometricMeasurements'], ensure_ascii=False, indent=2)
            print("\n[调试] 原始 JSON 数据（CephalometricMeasurements 部分）:")
            print(raw_json[:500] + "..." if len(raw_json) > 500 else raw_json)
            print()
    
    return jsonify({"status": "received"}), 200


@app.route('/get-result', methods=['GET'])
def get_result():
    """
    供前端轮询查询任务结果
    
    查询参数:
    - taskId: string (必填)
    
    返回:
    - 结果存在: 完整的回调 JSON (HTTP 200)
    - 结果不存在: {"status": "pending"} (HTTP 404)
    - 缺少参数: {"error": "taskId is required"} (HTTP 400)
    """
    task_id = request.args.get('taskId')
    
    if not task_id:
        return jsonify({"error": "taskId is required"}), 400
    
    if task_id in task_results:
        print("查询结果: taskId={}, 结果已存在".format(task_id))
        return jsonify(task_results[task_id]), 200
    else:
        return jsonify({"status": "pending"}), 404


if __name__ == '__main__':
    port = int(os.environ.get('PORT', os.environ.get('FLASK_PORT', '5000')))
    print("=" * 60)
    print("Flask 微型回调服务器启动中...")
    print("监听地址: 0.0.0.0:{}".format(port))
    print("前端页面: http://localhost:5000/")
    print("健康检查: http://localhost:5000/health")
    print("回调接口: http://localhost:5000/callback")
    print("结果查询: http://localhost:5000/get-result?taskId=xxx")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=False)

