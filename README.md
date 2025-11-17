# Xray Inference Service

口腔X光片AI推理服务 - 异步双进程架构

## 🚀 快速启动

```bash
# 一键启动（Redis + API + Worker + 前端）
docker-compose up -d

# 访问前端 Web 界面
http://localhost:5000/
```

**服务组成**: 
- Redis (消息队列)
- API (接收请求，端口: 18000)
- Worker (执行推理)
- Frontend (前端展示，端口: 5000)

**或使用 API 直接发送推理请求**:
```bash
curl -X POST http://localhost:18000/api/v1/analyze \
  -F "taskId=$(uuidgen)" \
  -F "taskType=pano" \
  -F "callbackUrl=http://localhost:5000/callback" \
  -F "image=@xray.jpg"
```

## 架构概述

本服务采用异步双进程模型：
- **API 服务 (P1)**: 接收HTTP请求，立即返回202
- **Worker 服务 (P2)**: 异步执行AI推理，完成后回调

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
├── web/                    # 前端服务
│   └── Xray_web/          
│       ├── app.py          # Flask 回调服务器
│       └── static/         # 前端静态文件
└── tools/                  # 工具脚本
```

## 详细使用

### 服务端口

启动后可访问以下端点：

| 服务 | 端口 | 地址 | 说明 |
|------|------|------|------|
| 前端界面 | 5000 | http://localhost:5000/ | Web UI 界面 |
| API 服务 | 18000 | http://localhost:18000/api/v1/analyze | 推理请求接口 |
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

## 开发状态

🚧 当前为项目初始化阶段，各模块正在开发中。

详细架构设计请参考：`vibe_coding/架构设计.md`
