# -*- coding: utf-8 -*-
"""
Flask 微型回调服务器
提供四个核心功能：
1. 静态文件服务：为前端页面提供 HTTP 访问
2. 图片上传接口：接收前端上传的图片，返回可访问的 URL
3. 回调接收接口：接收 AI 后端的异步回调
4. 结果查询接口：供前端轮询查询任务结果
"""
from flask import Flask, send_from_directory, jsonify, request
from werkzeug.utils import secure_filename
import os
import uuid

# 配置 Flask 应用的静态文件路径
app = Flask(__name__, 
            static_folder='static',
            static_url_path='/static')

# 配置上传目录
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'bmp', 'dcm'}

# 确保上传目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 全局内存存储：存储任务结果
task_results = {}


def allowed_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


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


@app.route('/upload', methods=['POST'])
def upload_file():
    """
    接收前端上传的图片文件，保存到本地，返回可访问的 URL
    
    请求格式：multipart/form-data
    - file: 图片文件
    
    返回格式 (JSON):
    - 成功: {"imageUrl": "http://host:port/uploads/filename.jpg"} (HTTP 200)
    - 失败: {"error": "错误信息"} (HTTP 400)
    """
    # 检查是否有文件
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    
    # 检查是否选择了文件
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    # 检查文件扩展名
    if not allowed_file(file.filename):
        return jsonify({"error": f"File type not allowed. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"}), 400
    
    # 生成唯一文件名
    file_ext = os.path.splitext(file.filename)[1].lower()
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
    
    try:
        # 保存文件
        file.save(file_path)
        
        # 生成可访问的 URL
        # 在 Docker 环境中，AI 后端需要通过 Flask 服务名访问
        # 使用 request.host 获取当前主机地址
        host = request.host
        image_url = f"http://{host}/uploads/{unique_filename}"
        
        print(f"文件上传成功: {file.filename} -> {file_path}")
        print(f"图片 URL: {image_url}")
        
        return jsonify({"imageUrl": image_url}), 200
    
    except Exception as e:
        print(f"文件保存失败: {e}")
        return jsonify({"error": f"Failed to save file: {str(e)}"}), 500


@app.route('/uploads/<filename>')
def serve_uploaded_file(filename):
    """
    提供上传文件的静态访问服务
    这样 AI 后端可以通过 HTTP 下载图片
    """
    return send_from_directory(UPLOAD_FOLDER, filename)


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
    print("上传目录: {}".format(UPLOAD_FOLDER))
    print("前端页面: http://localhost:5000/")
    print("健康检查: http://localhost:5000/health")
    print("图片上传: http://localhost:5000/upload")
    print("回调接口: http://localhost:5000/callback")
    print("结果查询: http://localhost:5000/get-result?taskId=xxx")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=False)

