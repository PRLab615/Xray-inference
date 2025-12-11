"""
计算指定图片文件的 SHA-256 哈希值。

使用方法（在项目根目录运行）：
python example/generate_hashes.py

脚本会输出 `liang.jpg` 和 `lin.jpg` 的哈希值，
你需要将这些哈希值复制到 `web/Xray_web/static/app.js` 文件中。
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent
IMAGES = {
    "liang": ROOT / "liang_ce.jpg",
    "lin": ROOT / "lin_ce.jpg",
}

def get_file_sha256(file_path: Path) -> str:
    """计算文件的 SHA-256 哈希值。"""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while True:
            data = f.read(65536)  # 64kb chunks
            if not data:
                break
            sha256.update(data)
    return sha256.hexdigest()


def main():
    print("=" * 50)
    print("请将以下哈希值复制到 `web/Xray_web/static/app.js` 的 `DEMO_HASHES` 对象中：")
    print("=" * 50)

    for key, path in IMAGES.items():
        if not path.exists():
            print(f'\n文件未找到，跳过: {path}')
            continue
        
        file_hash = get_file_sha256(path)
        print(f'\n// {path.name} 的哈希值')
        print(f'"{file_hash}": "{key}",')

    print("=" * 50)


if __name__ == "__main__":
    main()
