# Dockerfile for Xray Inference Service
# v3: 支持真实 AI 推理（包括深度学习依赖）
# 使用 bookworm 版本以确保包版本一致
FROM python:3.11-slim-bookworm

WORKDIR /app

# 配置阿里云 Debian 镜像源（解决网络问题）
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources || \
    (echo "deb https://mirrors.aliyun.com/debian/ bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
    echo "deb https://mirrors.aliyun.com/debian/ bookworm-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.aliyun.com/debian-security/ bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list)

# 安装 OpenCV 和 PyTorch 需要的系统依赖
# libGL.so.1 来自 libgl1，ultralytics 的 cv2 需要它
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .

# 配置国内 pip 镜像源（加速下载）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip config set install.trusted-host pypi.tuna.tsinghua.edu.cn

# 从 requirements.txt 安装所有依赖（包括深度学习框架）
# 注意：torch 和 ultralytics 的安装可能需要几分钟
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create upload directory
RUN mkdir -p /app/tmp/uploads

# Expose API port
EXPOSE 18000

# Default command (可以通过 docker-compose 覆盖)
CMD ["python", "main_api.py"]

