# Xray Inference Service

口腔X光片AI推理服务 - 异步双进程架构

## 🚀 快速启动

### 推理说明

如果本地无cached_weights模型权重的话，则只能返回 /example 下的Mock结果

### Linux 环境

```bash
# 一键启动（Redis + API + Worker + 前端）
docker-compose up -d

# 访问前端 Web 界面
http://localhost:5000/

```

### Windows/Mac 环境

```bash
# 使用 Windows/Mac 专用配置启动
docker-compose -f docker-compose.windows.yml up -d

# 访问前端 Web 界面
http://localhost:5000/
```

**服务组成**: 
- Redis (消息队列)
- API (接收请求，端口: 9010)
- Worker (执行推理)
- Frontend (前端展示，端口: 5000)

### Windows/Mac 环境

## 架构概述

本服务采用异步双进程模型：
- **API 服务 (P1)**: 接收HTTP请求，立即返回202
- **Worker 服务 (P2)**: 异步执行AI推理，完成后返回

## 目录结构

```
.
├── main_api.py                    # API 服务入口
├── cached_weights                  # 模型权重（如没有则只会返回mock值）
├── main_worker.py                  # Worker 服务入口
├── main_cli.py                     # CLI 批量推理入口
├── webui.py                        # 测试 Web UI
├── config.yaml                     # 全局配置
├── requirements.txt                # Python 依赖
├── Dockerfile                      # Docker 镜像构建文件
├── docker-compose.yml              # Linux 环境 Docker Compose 配置
├── docker-compose.windows.yml      # Windows/Mac 环境 Docker Compose 配置
├── server/                         # 服务层
│   ├── api.py                     # API 路由（同步/异步推理接口、计算接口）
│   ├── schemas.py                 # 数据模型（请求/响应 Schema）
│   ├── worker.py                  # Celery 配置
│   ├── tasks.py                   # 异步任务定义
│   ├── core/                      # 核心组件
│   │   ├── persistence.py         # 状态持久化
│   │   └── callback.py             # 回调管理
│   ├── utils/                     # 工具函数
│   │   └── image_downloader.py    # 图像下载工具
│   └── example_*.json             # 示例结果 JSON（全景片/侧位片/牙期检测）
├── pipelines/                      # AI 推理管道
│   ├── base_pipeline.py           # 基础管道抽象类
│   ├── pano/                      # 全景片推理管道
│   │   ├── pano_pipeline.py       # 全景片主管道
│   │   ├── modules/               # 各检测模块（牙齿分割、髁突检测等）
│   │   ├── utils/                 # 工具函数（报告生成、重新计算）
│   │   └── evaluation/            # 评估脚本
│   ├── ceph/                      # 侧位片推理管道
│   │   ├── ceph_pipeline.py       # 侧位片主管道
│   │   ├── modules/               # 关键点检测模块
│   │   ├── utils/                 # 工具函数（报告生成、重新计算）
│   │   └── evaluation/            # 评估脚本
│   └── dental_age/                # 牙期检测推理管道
│       └── dental_age_pipeline.py # 牙期检测主管道
├── web/                            # 前端服务
│   └── Xray_web/                  
│       ├── app.py                  # Flask 回调服务器
│       ├── static/                 # 前端静态文件（HTML/CSS/JS）
│       └── test/                   # 前端测试脚本
├── tools/                          # 工具脚本
│   ├── dicom_utils.py              # DICOM 文件处理工具/前端暂不能解析dicom数据
│   ├── timer.py                    # 性能计时工具
│   └── weight_fetcher.py           # 模型权重下载工具
├── models/                         # AI 模型文件存储目录
├── tmp/                            # 临时文件目录
├── docs/                           # 项目文档
└── vibe_coding/                    # 开发文档（架构设计、接口定义等）
    ├── 架构设计.md
    └── 接口定义.md
```

## 详细使用

### 服务端口

启动后可访问以下端点：

| 服务 | 端口 | 地址 | 说明 |
|------|------|------|------|
| 前端界面 | 5000 | http://localhost:5000/ | Web UI 界面 |
| API 服务 | 9010 | http://localhost:9010/api/v1/analyze | 推理请求接口 |
| 回调接口 | 5000 | http://localhost:5000/callback | 接收推理结果回调 |
| Redis | 6379 | localhost:6379 | 消息队列 |

### 查看服务状态


```bash
docker-compose ps      # 查看运行状态
docker-compose logs -f # 查看实时日志
docker-compose down    # 停止所有服务
```

### 本地开发（不使用Docker）

1. 安装依赖：
```bash
pip install -r requirements.txt
```

2. 启动 Redis：
```bash
redis-server
```

3. 启动 API 服务：
```bash
python main_api.py
```

4. 启动 Worker 服务：
```bash
python main_worker.py
```

## 配置说明

编辑 `config.yaml` 文件配置服务参数。

