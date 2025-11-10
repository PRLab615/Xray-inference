# Xray Inference Service

口腔X光片AI推理服务

## 架构概述

本服务采用异步双进程模型：
- **API 服务进程 (P1)**: 处理 HTTP 请求，立即返回 202 响应
- **Worker 服务进程 (P2)**: 执行 AI 计算，完成后触发回调

## 目录结构

```
.
├── main_api.py              # API 服务入口
├── main_worker.py           # Worker 服务入口
├── main_cli.py              # CLI 批量推理入口
├── webui.py                 # 测试 Web UI
├── config.yaml              # 全局配置
├── server/                  # 服务层
│   ├── api.py              # API 路由
│   ├── schemas.py          # 数据模型
│   ├── worker.py           # Celery 配置
│   ├── tasks.py            # 异步任务
│   └── core/               # 核心组件
│       ├── persistence.py  # 状态持久化
│       └── callback.py     # 回调管理
├── pipelines/              # AI 推理管道
└── tools/                  # 工具脚本
```

## 快速开始

### 使用 Docker Compose（推荐）

```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 本地开发

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

## 开发状态

🚧 当前为项目初始化阶段，各模块正在开发中。

详细架构设计请参考：`vibe_coding/架构设计.md`
