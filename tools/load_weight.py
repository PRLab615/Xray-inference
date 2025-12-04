import os
import boto3
import torch
from botocore.exceptions import ClientError
from urllib.parse import urlparse

# --- MinIO S3 配置（支持环境变量覆盖） ---
S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL', 'http://192.168.1.17:19000')
S3_ACCESS_KEY = os.getenv('S3_ACCESS_KEY', 'root')
S3_SECRET_KEY = os.getenv('S3_SECRET_KEY', 'Sitonholy@2023')
# 假设 'teeth' 是 Bucket 名称。如果 'teeth' 只是文件夹，请修改这里为实际 Bucket 名称
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', 'teeth')

# 本地缓存权重的默认目录 (避免污染项目根目录)
LOCAL_WEIGHTS_DIR = './cached_weights'


def get_s3_client():
    """
    初始化并返回 S3 客户端
    """
    return boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY
    )


def load_model_weights(s3_relative_path: str, device: str = 'cpu', force_download: bool = False):
    """
    从 MinIO 加载权重。如果本地不存在，则自动下载。

    Args:
        s3_relative_path (str): S3 中的相对路径 (例如: 'weights/cephalometric/best_model.pth')
                                注意：不要包含 Bucket 名称。
        device (str): 加载权重的设备 ('cpu' 或 'cuda')
        force_download (bool): 是否强制重新下载 (即使本地已有文件)

    Returns:
        state_dict: PyTorch 模型权重字典 (如果加载失败返回 None)
    """

    # 1. 构建本地保存路径
    # 保持与 S3 相同的目录结构，方便管理
    local_file_path = os.path.join(LOCAL_WEIGHTS_DIR, s3_relative_path)
    local_folder = os.path.dirname(local_file_path)

    # 确保本地目录存在
    if not os.path.exists(local_folder):
        os.makedirs(local_folder)

    # 2. 检查本地是否已有缓存
    file_exists = os.path.exists(local_file_path)

    if not file_exists or force_download:
        print(f"[Info] 开始从 MinIO 下载权重: {s3_relative_path} ...")
        s3 = get_s3_client()
        try:
            # 这里的 s3_relative_path 就是 Key
            s3.download_file(S3_BUCKET_NAME, s3_relative_path, local_file_path)
            print(f"[Success] 下载完成，已保存至: {local_file_path}")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == "404":
                print(f"[Error] S3 上找不到文件: Bucket={S3_BUCKET_NAME}, Key={s3_relative_path}")
            else:
                print(f"[Error] 下载出错: {e}")
            # 下载失败，如果本地有旧文件也可能无法使用，建议返回 None 或抛出异常
            return None
    else:
        print(f"[Info] 使用本地缓存权重: {local_file_path}")

    # 3. 加载权重到内存 (PyTorch)
    try:
        print(f"[Info] 正在加载权重到 {device}...")
        # map_location 确保即使在没有 GPU 的机器上也能加载 GPU 训练的权重
        weights = torch.load(local_file_path, map_location=device)
        return weights
    except Exception as e:
        print(f"[Error] 权重文件加载失败 (文件可能已损坏): {e}")
        return None


# --- 使用示例 (Main Block) ---
if __name__ == "__main__":
    # 这里演示如何调用
    # 场景 1: 加载侧位片 (Cephalometric) 权重
    # 注意：这里的路径是你在 S3 Bucket 里的 Key，去掉了 Bucket Name 'teeth'
    ceph_path_placeholder = "weights/cephalometric/model_v1_epoch100.pth"

    print("-" * 30)
    print("尝试加载侧位片模型...")
    ceph_weights = load_model_weights(ceph_path_placeholder, device='cpu')

    if ceph_weights:
        print("侧位片模型加载成功！可以传给 model.load_state_dict() 了。")
    else:
        print("侧位片模型加载失败，请检查路径或网络。")

    # 场景 2: 加载全景片 (Panoramic) 权重
    pano_path_placeholder = "weights/panoramic/yolo_best.pt"

    print("-" * 30)
    print("尝试加载全景片模型...")
    pano_weights = load_model_weights(pano_path_placeholder, device='cpu')