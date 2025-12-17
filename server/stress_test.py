# -*- coding: utf-8 -*-
import requests
import os
import random
import time
import json
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
# functools.partial removed - not needed after Python 3.6 compatibility fix

# ================= 配置区域 =================
# 后端 API 地址
# ⚠️ 如果在同一台服务器上运行，建议使用 localhost
API_BASE_URL = "http://localhost:9010"  # 后端API地址，请根据实际情况修改端口

# ===== 图片访问模式配置 =====
# 模式1: "local_server" - 启动本地HTTP服务器（适用于本地测试）
# 模式2: "remote_url" - 使用已有的图片URL（适用于后端无法访问本地网络的情况）
IMAGE_MODE = "local_server"  # 可选: "local_server" 或 "remote_url"

# 【模式1】本地HTTP服务器配置（仅在 IMAGE_MODE="local_server" 时使用）
PANO_IMAGE_DIR = r"/AAA_615/dataset/Xray/pano"  # 全景片文件夹路径
CEPH_IMAGE_DIR = r"/AAA_615/dataset/Xray/ceph"  # 侧位片文件夹路径
DICOM_IMAGE_DIR = r"/AAA_615/dataset/Xray/dicom"  # DICOM文件夹路径（支持 .dcm 文件）

# ⚠️ IMAGE_SERVER_HOST 配置说明：
# - Linux + docker-compose.linux.yml (host网络): 使用 "127.0.0.1" 或 "0.0.0.0"
# - Linux + docker-compose.yml (桥接网络): 使用宿主机实际 IP（如 "192.168.1.100"）或 "host.docker.internal"
# - Windows/Mac + docker-compose.yml: 使用 "host.docker.internal"
IMAGE_SERVER_HOST = "0.0.0.0"  # 监听所有网卡，方便 Docker 容器访问
IMAGE_SERVER_PORT = 9999  # 本地服务器端口

# 用于生成图片 URL 的地址（后端下载图片时使用）
# 如果后端运行在 Docker 桥接网络中，需要改成宿主机 IP 或 host.docker.internal
import socket
def _get_host_ip():
    """获取本机 IP 地址（用于 Docker 桥接网络场景）"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

# 自动检测：如果环境变量 DOCKER_BRIDGE 设置为 1，使用宿主机 IP
import os
if os.environ.get("DOCKER_BRIDGE") == "1":
    IMAGE_SERVER_URL_HOST = _get_host_ip()
else:
    IMAGE_SERVER_URL_HOST = IMAGE_SERVER_HOST if IMAGE_SERVER_HOST != "0.0.0.0" else "127.0.0.1"

IMAGE_SERVER_BASE_URL = "http://{}:{}".format(IMAGE_SERVER_URL_HOST, IMAGE_SERVER_PORT)  # 自动生成

# 【模式2】远程URL配置（仅在 IMAGE_MODE="remote_url" 时使用）
# 将图片文件名列表和URL前缀配置在这里
# 例如：将图片上传到后端服务器的静态文件目录，或使用公共图床
REMOTE_PANO_URL_PREFIX = "http://192.168.1.23:9010/static/test_images/pano"  # 全景片URL前缀
REMOTE_CEPH_URL_PREFIX = "http://192.168.1.23:9010/static/test_images/ceph"  # 侧位片URL前缀
REMOTE_DICOM_URL_PREFIX = "http://192.168.1.23:9010/static/test_images/dicom"  # DICOM URL前缀

# 图片文件名列表（模式2使用，手动列出可用的图片文件名）
REMOTE_PANO_IMAGES = [
    "4324.png", "4340.png", "2038.png", "4242.png"  # 示例，请根据实际情况修改
]
REMOTE_CEPH_IMAGES = [
    "ceph_001.png", "ceph_002.png"  # 示例，请根据实际情况修改
]
REMOTE_DICOM_IMAGES = [
    "sample.dcm"  # 示例，请根据实际情况修改
]

# 并发配置
CONCURRENCY = 10       # 同时有多少个请求在跑 (并发数)
TOTAL_REQUESTS = 50    # 总共要发送多少个请求

# 任务类型权重 (可以调整被随机选中的概率)
# 格式: (任务类型, 权重)
TASK_DISTRIBUTION = [
    ("analyze_pano", 3),        # 全景分析 (imageUrl)
    ("analyze_ceph", 3),        # 侧位分析 (imageUrl)
    ("analyze_dental_stage", 2),# 牙期检测 (使用全景图)
    ("analyze_pano_dicom", 2),  # 全景分析 (dicomUrl) - DICOM格式
    ("analyze_ceph_dicom", 2),  # 侧位分析 (dicomUrl) - DICOM格式，患者信息从DICOM解析
    ("recalculate_pano", 1),    # 全景重算
    ("recalculate_ceph", 1)     # 侧位重算
]

# 请求超时设置（秒）
REQUEST_TIMEOUT = 180  # 3分钟超时
# ===========================================

# ================= 图片服务器相关 =================
class DirectoryHTTPRequestHandler(SimpleHTTPRequestHandler):
    """
    Custom HTTP request handler that serves files from a specified directory.
    Compatible with Python 3.6+ (the 'directory' parameter was added in 3.7)
    """
    # Class-level variable to store the directory
    _serve_directory = None
    
    def translate_path(self, path):
        """Translate URL path to filesystem path, using our custom directory."""
        # Get the default path first
        path = SimpleHTTPRequestHandler.translate_path(self, path)
        # Replace the current working directory with our serve directory
        if self._serve_directory:
            # Get the relative path from cwd
            relpath = os.path.relpath(path, os.getcwd())
            # Join with our serve directory
            path = os.path.join(self._serve_directory, relpath)
        return path
    
    def log_message(self, format, *args):
        """Suppress log messages to reduce noise during stress test."""
        pass


def start_image_server(pano_dir, ceph_dir, dicom_dir=None):
    """
    启动一个简单的HTTP服务器来提供图片访问
    返回 (server_thread, image_list)
    
    Args:
        pano_dir: 全景片文件夹路径
        ceph_dir: 侧位片文件夹路径
        dicom_dir: DICOM文件夹路径（可选）
    """
    # 创建临时目录结构：将文件夹的图片映射到 /pano, /ceph, /dicom 路径
    import tempfile
    import shutil
    
    temp_dir = tempfile.mkdtemp(prefix="stress_test_images_")
    pano_serve_dir = os.path.join(temp_dir, "pano")
    ceph_serve_dir = os.path.join(temp_dir, "ceph")
    dicom_serve_dir = os.path.join(temp_dir, "dicom")
    
    # 复制图片到临时目录（或创建符号链接）
    if os.path.exists(pano_dir):
        shutil.copytree(pano_dir, pano_serve_dir)
    else:
        os.makedirs(pano_serve_dir)
        
    if os.path.exists(ceph_dir):
        shutil.copytree(ceph_dir, ceph_serve_dir)
    else:
        os.makedirs(ceph_serve_dir)
    
    # 复制DICOM文件到临时目录
    if dicom_dir and os.path.exists(dicom_dir):
        shutil.copytree(dicom_dir, dicom_serve_dir)
    else:
        os.makedirs(dicom_serve_dir)
    
    # 获取图片列表
    pano_images = ["pano/{}".format(f) for f in os.listdir(pano_serve_dir) 
                   if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp'))] if os.path.exists(pano_serve_dir) else []
    ceph_images = ["ceph/{}".format(f) for f in os.listdir(ceph_serve_dir) 
                   if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp'))] if os.path.exists(ceph_serve_dir) else []
    # DICOM文件列表（支持 .dcm 扩展名）
    dicom_images = ["dicom/{}".format(f) for f in os.listdir(dicom_serve_dir) 
                    if f.lower().endswith(('.dcm', '.dicom'))] if os.path.exists(dicom_serve_dir) else []
    
    image_list = {
        "pano": pano_images,
        "ceph": ceph_images,
        "dicom": dicom_images,
        "temp_dir": temp_dir
    }
    
    # 启动HTTP服务器 (Python 3.6 compatible)
    # Set the directory at class level before creating the server
    DirectoryHTTPRequestHandler._serve_directory = temp_dir
    server = HTTPServer((IMAGE_SERVER_HOST, IMAGE_SERVER_PORT), DirectoryHTTPRequestHandler)
    
    def serve():
        print("📡 Image server starting on {}".format(IMAGE_SERVER_BASE_URL))
        print("   - Pano images: {}".format(len(pano_images)))
        print("   - Ceph images: {}".format(len(ceph_images)))
        print("   - DICOM files: {}".format(len(dicom_images)))
        server.serve_forever()

    server_thread = threading.Thread(target=serve, daemon=True)
    server_thread.start()
    time.sleep(1)  # 等待服务器启动
    
    return server, image_list


def get_random_image_url(image_list, image_type):
    """
    获取随机图片URL
    
    Args:
        image_list: 图片列表字典 (在local_server模式下) 或 None (在remote_url模式下)
        image_type: "pano", "ceph", 或 "dicom"
    
    Returns:
        完整的图片URL，如果没有图片则返回None
    """
    if IMAGE_MODE == "remote_url":
        # 模式2：使用远程URL
        if image_type == "pano":
            if not REMOTE_PANO_IMAGES:
                return None
            filename = random.choice(REMOTE_PANO_IMAGES)
            return "{}/{}".format(REMOTE_PANO_URL_PREFIX, filename)
        elif image_type == "ceph":
            if not REMOTE_CEPH_IMAGES:
                return None
            filename = random.choice(REMOTE_CEPH_IMAGES)
            return "{}/{}".format(REMOTE_CEPH_URL_PREFIX, filename)
        elif image_type == "dicom":
            if not REMOTE_DICOM_IMAGES:
                return None
            filename = random.choice(REMOTE_DICOM_IMAGES)
            return "{}/{}".format(REMOTE_DICOM_URL_PREFIX, filename)
        else:
            return None
    else:
        # 模式1：使用本地服务器
        images = image_list.get(image_type, [])
        if not images:
            return None
        image_path = random.choice(images)
        return "{}/{}".format(IMAGE_SERVER_BASE_URL, image_path)

# ================= 任务执行相关 =================
def generate_mock_pano_recalculate_data():
    """生成模拟的全景片重算数据（符合接口定义格式）"""
    return {
        "taskId": str(uuid.uuid4()),
        "data": {  # 必须包装在 "data" 字段中
            "Metadata": {
                "ImageName": "stress_test_pano.jpg",
                "DiagnosisID": "TEST-{}".format(uuid.uuid4().hex[:8]),
                "AnalysisTime": datetime.now().isoformat()
            },
            "AnatomyResults": [],
            "JointAndMandible": {},
            "MaxillarySinus": [],
            "PeriodontalCondition": {},
            "MissingTeeth": [],
            "ThirdMolarSummary": {},
            "ImplantAnalysis": {},
            "RootTipDensityAnalysis": {},
            "ToothAnalysis": []
        }
    }


def generate_mock_ceph_recalculate_data():
    """生成模拟的侧位片重算数据（符合接口定义格式）"""
    return {
        "taskId": str(uuid.uuid4()),
        "data": {  # 必须包装在 "data" 字段中
            "ImageSpacing": {"X": 0.1, "Y": 0.1, "Unit": "mm"},
            "VisibilityMetrics": {},
            "PatientInformation": {
                "Gender": "Male",
                "DentalAgeStage": "Permanent"
            },
            "LandmarkPositions": {
                "Landmarks": [],
                "TotalLandmarks": 0,
                "DetectedLandmarks": 0,
                "MissingLandmarks": 0
            },
            "CephalometricMeasurements": {
                "AllMeasurements": []
            }
        },
        "patientInfo": {  # 侧位片必填
            "gender": "Male",
            "DentalAgeStage": "Permanent"
        }
    }


def run_task(task_id_seq, image_list):
    """
    执行单个任务
    
    Args:
        task_id_seq: 任务序号
        image_list: 图片列表字典
    
    Returns:
        任务执行结果字符串
    """
    # 根据权重随机选择一个任务类型
    task_types = [t[0] for t in TASK_DISTRIBUTION]
    weights = [t[1] for t in TASK_DISTRIBUTION]
    task_type = random.choices(task_types, weights=weights, k=1)[0]
    
    start_time = time.time()
    task_id = str(uuid.uuid4())
    
    try:
        # --- 构造请求 ---
        if task_type == "analyze_pano":
            url = "{}/api/v1/analyze".format(API_BASE_URL)
            image_url = get_random_image_url(image_list, "pano")
            if not image_url:
                return "[{}] Request #{} | SKIPPED (No Pano Images)".format(task_type, task_id_seq)
            
            payload = {
                "taskId": task_id,
                "taskType": "panoramic",
                "imageUrl": image_url,
                "metadata": {"source": "stress_test", "seq": task_id_seq}
            }
            
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)

        elif task_type == "analyze_ceph":
            url = "{}/api/v1/analyze".format(API_BASE_URL)
            image_url = get_random_image_url(image_list, "ceph")
            if not image_url:
                return "[{}] Request #{} | SKIPPED (No Ceph Images)".format(task_type, task_id_seq)
            
            payload = {
                "taskId": task_id,
                "taskType": "cephalometric",
                "imageUrl": image_url,
                "metadata": {"source": "stress_test", "seq": task_id_seq},
                "patientInfo": {
                    "gender": random.choice(["Male", "Female"]),  # 注意首字母大写
                    "DentalAgeStage": random.choice(["Permanent", "Mixed"])  # 必填字段
                }
            }
            
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)

        elif task_type == "analyze_dental_stage":
            url = "{}/api/v1/analyze".format(API_BASE_URL)
            image_url = get_random_image_url(image_list, "pano")
            if not image_url:
                return "[{}] Request #{} | SKIPPED (No Pano Images)".format(task_type, task_id_seq)
            
            payload = {
                "taskId": task_id,
                "taskType": "dental_age_stage",
                "imageUrl": image_url,
                "metadata": {"source": "stress_test", "seq": task_id_seq}
            }
            
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)

        elif task_type == "analyze_pano_dicom":
            # 全景片 DICOM 分析（使用 dicomUrl）
            url = "{}/api/v1/analyze".format(API_BASE_URL)
            dicom_url = get_random_image_url(image_list, "dicom")
            if not dicom_url:
                return "[{}] Request #{} | SKIPPED (No DICOM Files)".format(task_type, task_id_seq)
            
            payload = {
                "taskId": task_id,
                "taskType": "panoramic",
                "dicomUrl": dicom_url,  # 使用 dicomUrl 而非 imageUrl
                "metadata": {"source": "stress_test", "seq": task_id_seq, "format": "dicom"}
            }
            
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)

        elif task_type == "analyze_ceph_dicom":
            # 侧位片 DICOM 分析（使用 dicomUrl，患者信息从 DICOM 解析）
            url = "{}/api/v1/analyze".format(API_BASE_URL)
            dicom_url = get_random_image_url(image_list, "dicom")
            if not dicom_url:
                return "[{}] Request #{} | SKIPPED (No DICOM Files)".format(task_type, task_id_seq)
            
            # 使用 dicomUrl 时，patientInfo 可选（后端从 DICOM 解析）
            # 但为了兼容性，这里还是提供 patientInfo 作为备用
            payload = {
                "taskId": task_id,
                "taskType": "cephalometric",
                "dicomUrl": dicom_url,  # 使用 dicomUrl 而非 imageUrl
                "metadata": {"source": "stress_test", "seq": task_id_seq, "format": "dicom"},
                # patientInfo 可选，如果 DICOM 中没有患者信息，后端会报错
                # 这里提供备用值，防止 DICOM 解析失败
                "patientInfo": {
                    "gender": random.choice(["Male", "Female"]),
                    "DentalAgeStage": random.choice(["Permanent", "Mixed"])
                }
            }
            
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)

        elif task_type == "recalculate_pano":
            url = "{}/api/v1/measurements/pano/recalculate".format(API_BASE_URL)
            payload = generate_mock_pano_recalculate_data()
            
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)

        elif task_type == "recalculate_ceph":
            url = "{}/api/v1/measurements/ceph/recalculate".format(API_BASE_URL)
            payload = generate_mock_ceph_recalculate_data()
            
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        
        else:
            return "[{}] Request #{} | ERROR: Unknown task type".format(task_type, task_id_seq)

        # --- 处理响应 ---
        elapsed = time.time() - start_time
        content_size_kb = len(response.content) / 1024
        
        # 判断是否成功
        if response.status_code == 200:
            status = "✅ SUCCESS"
            # 尝试解析响应，检查是否真的成功
            try:
                result = response.json()
                if result.get("status") == "FAILED":
                    error_info = result.get('error', {})
                    error_msg = error_info.get('message', 'unknown')
                    status = "⚠️  FAILED (API error: {})".format(error_msg[:40])
            except:
                pass
        else:
            status = "❌ FAILED"
            # 尝试获取错误详情
            try:
                error_detail = response.json()
                if 'message' in error_detail:
                    error_msg = error_detail['message'][:60]
                    status = "❌ FAILED ({})".format(error_msg)
            except:
                pass
        
        return ("[{:25}] Req #{:3} | {:50} | "
                "Time: {:6.2f}s | Size: {:7.2f} KB | Code: {}".format(
                    task_type, task_id_seq, status, elapsed, content_size_kb, response.status_code))

    except requests.exceptions.Timeout:
        elapsed = time.time() - start_time
        return "[{:25}] Req #{:3} | ⏱️  TIMEOUT           | Time: {:6.2f}s".format(task_type, task_id_seq, elapsed)
        
    except Exception as e:
        elapsed = time.time() - start_time
        return "[{:25}] Req #{:3} | 💥 ERROR             | Time: {:6.2f}s | {}".format(task_type, task_id_seq, elapsed, str(e)[:50])

# ================= 网络测试相关 =================
def test_network_connectivity(image_list):
    """
    测试网络连接性
    
    检查：
    1. 图片URL是否可访问（根据模式不同）
    2. 后端API是否可访问
    3. 后端是否能访问图片URL（关键！）
    """
    print("🔍 Testing network connectivity...")
    print("   Mode: {}".format(IMAGE_MODE))
    print("-" * 80)
    
    # 测试1：测试图片URL访问
    if IMAGE_MODE == "local_server":
        print("1️⃣  Testing local access to image server...")
        try:
            response = requests.get(IMAGE_SERVER_BASE_URL, timeout=5)
            print("   ✅ Local image server is accessible from this machine")
        except Exception as e:
            print("   ❌ Cannot access local image server: {}".format(e))
            print("   💡 Make sure the image server is running on {}".format(IMAGE_SERVER_BASE_URL))
    else:
        print("1️⃣  Testing remote image URL accessibility...")
        test_images = []
        if REMOTE_PANO_IMAGES:
            test_images.append("{}/{}".format(REMOTE_PANO_URL_PREFIX, REMOTE_PANO_IMAGES[0]))
        if REMOTE_CEPH_IMAGES:
            test_images.append("{}/{}".format(REMOTE_CEPH_URL_PREFIX, REMOTE_CEPH_IMAGES[0]))
        
        if not test_images:
            print("   ⚠️  No remote images configured")
        else:
            test_url = test_images[0]
            print("   Testing: {}".format(test_url))
            try:
                response = requests.head(test_url, timeout=5)
                if response.status_code == 200:
                    print("   ✅ Remote image URL is accessible from this machine")
                else:
                    print("   ⚠️  Got status code: {}".format(response.status_code))
            except Exception as e:
                print("   ❌ Cannot access remote image URL: {}".format(e))
                print("   💡 Make sure images are uploaded to the remote server")
    
    # 测试2：访问后端API
    print("2️⃣  Testing access to backend API...")
    try:
        response = requests.get("{}/".format(API_BASE_URL), timeout=10)
        print("   ✅ Backend API is accessible (Status: {})".format(response.status_code))
    except Exception as e:
        print("   ⚠️  Backend API test: {}".format(str(e)[:80]))
        print("   ℹ️  This might be OK if root endpoint is not implemented")
    
    # 测试3：后端能否访问图片URL（通过发送一个测试请求）
    print("3️⃣  Testing if backend can download images/DICOM...")
    print("   ℹ️  This is the CRITICAL test - backend must be able to download images!")
    
    # 优先测试 DICOM（如果有），否则测试普通图片
    test_image_url = None
    test_is_dicom = False
    
    if (IMAGE_MODE == "local_server" and image_list.get("dicom")) or (IMAGE_MODE == "remote_url" and REMOTE_DICOM_IMAGES):
        test_image_url = get_random_image_url(image_list, "dicom")
        test_is_dicom = True
    elif (IMAGE_MODE == "local_server" and image_list.get("pano")) or (IMAGE_MODE == "remote_url" and REMOTE_PANO_IMAGES):
        test_image_url = get_random_image_url(image_list, "pano")
    else:
        test_image_url = get_random_image_url(image_list, "ceph")
    
    if not test_image_url:
        print("   ⚠️  No images/DICOM available for testing")
        return False
    
    print("   📷 Test {} URL: {}".format("DICOM" if test_is_dicom else "image", test_image_url))
    
    try:
        # 根据是否是 DICOM 构造不同的请求
        if test_is_dicom:
            test_payload = {
                "taskId": str(uuid.uuid4()),
                "taskType": "panoramic",
                "dicomUrl": test_image_url,  # 使用 dicomUrl
                "metadata": {"test": "connectivity", "format": "dicom"}
            }
        else:
            test_payload = {
                "taskId": str(uuid.uuid4()),
                "taskType": "panoramic" if "pano" in test_image_url else "cephalometric",
                "imageUrl": test_image_url,
                "metadata": {"test": "connectivity"},
                "patientInfo": {"gender": "Male", "DentalAgeStage": "Permanent"} if "ceph" in test_image_url else None
            }
        
        response = requests.post("{}/api/v1/analyze".format(API_BASE_URL), json=test_payload, timeout=30)
        
        if response.status_code == 200:
            print("   ✅ Backend can access image server and process requests!")
            return True
        else:
            print("   ❌ Backend returned error (Status: {})".format(response.status_code))
            try:
                error_info = response.json()
                print("   📋 Error details: {}".format(error_info.get('message', 'unknown')))
                if 'Cannot download image' in str(error_info):
                    print("   💡 SOLUTION: Backend cannot access your image server!")
                    print("      - Option 1: Make sure {} is accessible from backend server".format(IMAGE_SERVER_HOST))
                    print("      - Option 2: Change IMAGE_SERVER_HOST to an IP that backend can access")
                    print("      - Option 3: Use a public image hosting service instead")
            except:
                pass
            return False
            
    except Exception as e:
        print("   ❌ Test request failed: {}".format(e))
        return False


# ================= 主函数 =================
def main():
    print("=" * 80)
    print("🚀 X-Ray Inference API - Stress Test Tool")
    print("=" * 80)
    print("📋 Configuration:")
    print("   - API Endpoint    : {}".format(API_BASE_URL))
    print("   - Image Mode      : {}".format(IMAGE_MODE))
    print("   - Total Requests  : {}".format(TOTAL_REQUESTS))
    print("   - Concurrency     : {}".format(CONCURRENCY))
    print("   - Request Timeout : {}s".format(REQUEST_TIMEOUT))
    
    if IMAGE_MODE == "local_server":
        print("   - Pano Image Dir  : {}".format(PANO_IMAGE_DIR))
        print("   - Ceph Image Dir  : {}".format(CEPH_IMAGE_DIR))
        print("   - DICOM Image Dir : {}".format(DICOM_IMAGE_DIR))
        print("   - Image Server    : http://{}:{}".format(IMAGE_SERVER_HOST, IMAGE_SERVER_PORT))
    else:
        print("   - Pano URL Prefix : {}".format(REMOTE_PANO_URL_PREFIX))
        print("   - Ceph URL Prefix : {}".format(REMOTE_CEPH_URL_PREFIX))
        print("   - DICOM URL Prefix: {}".format(REMOTE_DICOM_URL_PREFIX))
        print("   - Pano Images     : {} configured".format(len(REMOTE_PANO_IMAGES)))
        print("   - Ceph Images     : {} configured".format(len(REMOTE_CEPH_IMAGES)))
        print("   - DICOM Images    : {} configured".format(len(REMOTE_DICOM_IMAGES)))
    print()
    
    # 根据模式初始化
    image_server = None
    image_list = {}
    
    if IMAGE_MODE == "local_server":
        # 模式1：启动本地HTTP服务器
        # 检查图片目录（至少需要一个目录存在）
        dirs_exist = [
            os.path.exists(PANO_IMAGE_DIR),
            os.path.exists(CEPH_IMAGE_DIR),
            os.path.exists(DICOM_IMAGE_DIR)
        ]
        if not any(dirs_exist):
            print("❌ ERROR: None of the image directories exist!")
            print("   PANO_IMAGE_DIR: {} (exists: {})".format(PANO_IMAGE_DIR, dirs_exist[0]))
            print("   CEPH_IMAGE_DIR: {} (exists: {})".format(CEPH_IMAGE_DIR, dirs_exist[1]))
            print("   DICOM_IMAGE_DIR: {} (exists: {})".format(DICOM_IMAGE_DIR, dirs_exist[2]))
            print("   Please update the paths in the configuration section.")
            return
        
        # 启动图片服务器
        print("📡 Starting local image server...")
        try:
            image_server, image_list = start_image_server(PANO_IMAGE_DIR, CEPH_IMAGE_DIR, DICOM_IMAGE_DIR)
        except Exception as e:
            print("❌ Failed to start image server: {}".format(e))
            return
        
        if not image_list["pano"] and not image_list["ceph"] and not image_list["dicom"]:
            print("❌ ERROR: No images/DICOM files found in any directory!")
            return
    else:
        # 模式2：使用远程URL
        if not REMOTE_PANO_IMAGES and not REMOTE_CEPH_IMAGES and not REMOTE_DICOM_IMAGES:
            print("❌ ERROR: No remote images configured!")
            print("   Please update REMOTE_PANO_IMAGES, REMOTE_CEPH_IMAGES, or REMOTE_DICOM_IMAGES in the configuration.")
            return
        
        print("✅ Using remote image URLs (no local server needed)")
        # 创建虚拟image_list用于兼容性
        image_list = {
            "pano": REMOTE_PANO_IMAGES,
            "ceph": REMOTE_CEPH_IMAGES,
            "dicom": REMOTE_DICOM_IMAGES,
            "temp_dir": None
        }
    
    print()
    print("📊 Task Distribution:")
    for task_type, weight in TASK_DISTRIBUTION:
        percentage = (weight / sum(t[1] for t in TASK_DISTRIBUTION)) * 100
        print("   - {:25}: {:2} ({:.1f}%)".format(task_type, weight, percentage))
    print()
    print("=" * 80)
    
    # 网络连接测试
    if not test_network_connectivity(image_list):
        print()
        print("⚠️  WARNING: Network connectivity test failed!")
        print("   The stress test may fail. Do you want to continue? (y/n)")
        try:
            user_input = input("   > ").strip().lower()
            if user_input != 'y':
                print("❌ Stress test cancelled.")
                return
        except:
            # 非交互模式，继续执行
            pass
    
    print()
    print("=" * 80)
    print("🏁 Starting stress test...")
    print("=" * 80)

    start_global = time.time()
    results = {
        "success": 0,
        "failed": 0,
        "timeout": 0,
        "error": 0,
        "skipped": 0
    }
    
    # 执行并发测试
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = [executor.submit(run_task, i, image_list) for i in range(1, TOTAL_REQUESTS + 1)]
        
        for future in as_completed(futures):
            result_msg = future.result()
            print(result_msg)
            
            # 统计结果
            if "SUCCESS" in result_msg:
                results["success"] += 1
            elif "TIMEOUT" in result_msg:
                results["timeout"] += 1
            elif "SKIPPED" in result_msg:
                results["skipped"] += 1
            elif "FAILED" in result_msg or "ERROR" in result_msg:
                if "FAILED (API" in result_msg:
                    results["failed"] += 1
                else:
                    results["error"] += 1

    total_time = time.time() - start_global
    
    # 打印统计结果
    print()
    print("=" * 80)
    print("📊 Test Results Summary")
    print("=" * 80)
    print("⏱️  Total Time     : {:.2f} seconds".format(total_time))
    print("📈 TPS            : {:.2f} requests/sec".format(TOTAL_REQUESTS / total_time))
    print("⏱️  Avg Time/Req  : {:.2f} seconds".format(total_time / TOTAL_REQUESTS))
    print()
    print("✅ Success        : {:3} ({:5.1f}%)".format(results['success'], results['success']/TOTAL_REQUESTS*100))
    print("❌ Failed         : {:3} ({:5.1f}%)".format(results['failed'], results['failed']/TOTAL_REQUESTS*100))
    print("⏱️  Timeout       : {:3} ({:5.1f}%)".format(results['timeout'], results['timeout']/TOTAL_REQUESTS*100))
    print("💥 Error          : {:3} ({:5.1f}%)".format(results['error'], results['error']/TOTAL_REQUESTS*100))
    print("⏭️  Skipped       : {:3} ({:5.1f}%)".format(results['skipped'], results['skipped']/TOTAL_REQUESTS*100))
    print("=" * 80)
    
    # 停止图片服务器（仅在local_server模式下）
    if IMAGE_MODE == "local_server" and image_server:
        try:
            print()
            print("🛑 Shutting down image server...")
            image_server.shutdown()
            # 清理临时目录
            import shutil
            if image_list.get("temp_dir"):
                shutil.rmtree(image_list["temp_dir"], ignore_errors=True)
            print("✅ Cleanup completed")
        except Exception as e:
            print("⚠️  Cleanup warning: {}".format(e))


if __name__ == "__main__":
    main()