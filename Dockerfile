# Dockerfile for Xray Inference Service
# 第一版：轻量级镜像，用于步骤3-8的开发测试
FROM python:3.11-slim

WORKDIR /app

# 暂时只安装基本依赖（OpenCV 相关依赖在真正使用时再添加）
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .

# 配置国内 pip 镜像源（加速下载）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip config set install.trusted-host pypi.tuna.tsinghua.edu.cn

# 先安装基础依赖（不安装 OpenCV，避免编译问题）
RUN pip install --no-cache-dir \
    fastapi>=0.104.0 \
    uvicorn[standard]>=0.24.0 \
    pydantic>=2.8.0 \
    pydantic-settings>=2.1.0 \
    celery>=5.3.0 \
    redis>=5.0.0 \
    httpx>=0.25.0 \
    requests>=2.31.0 \
    pyyaml>=6.0 \
    python-multipart>=0.0.6 \
    python-dotenv>=1.0.0 \
    flask

# 注意：numpy, opencv-python, pillow 在真正需要 AI 推理时再安装
# 第一版使用 mock 推理，不需要这些依赖

# Copy application code
COPY . .

# Create upload directory
RUN mkdir -p /app/tmp/uploads

# Expose API port
EXPOSE 8000

# Default command (可以通过 docker-compose 覆盖)
CMD ["python", "main_api.py"]

