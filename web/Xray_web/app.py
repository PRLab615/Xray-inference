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
    
    print(f"收到回调: taskId={task_id}, status={data.get('status')}")
    
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
        print(f"查询结果: taskId={task_id}, 结果已存在")
        return jsonify(task_results[task_id]), 200
    else:
        return jsonify({"status": "pending"}), 404


if __name__ == '__main__':
    print("=" * 60)
    print("Flask 微型回调服务器启动中...")
    print("监听地址: 0.0.0.0:5000")
    print("前端页面: http://localhost:5000/")
    print("健康检查: http://localhost:5000/health")
    print("回调接口: http://localhost:5000/callback")
    print("结果查询: http://localhost:5000/get-result?taskId=xxx")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=False)

