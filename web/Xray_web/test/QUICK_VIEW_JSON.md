# 快速查看 JSON 输出指南

## 步骤 1: 获取 taskId

### 方法 1: 查看 Flask 服务器日志（最简单）
```bash
# 在运行 Flask 服务器的终端中，查找类似这样的日志:
收到回调: taskId=abc123-def456-ghi789, status=SUCCESS
```

### 方法 2: 浏览器控制台
```javascript
// 打开浏览器开发者工具 (F12)，在 Console 中执行:
console.log(appState.currentTaskId)
```

### 方法 3: 浏览器网络请求
1. 打开浏览器开发者工具 (F12)
2. 切换到 Network 标签
3. 查找 `/get-result?taskId=xxx` 请求
4. 复制 taskId

## 步骤 2: 运行测试脚本

```bash
cd /app/web/Xray_web
python test_ceph_json.py <taskId>
```

示例:
```bash
python test_ceph_json.py abc123-def456-ghi789
```

## 步骤 3: 查看 JSON 输出

### 方法 1: 直接查看控制台输出
脚本会在控制台自动打印 `CephalometricMeasurements` 部分的 JSON

### 方法 2: 查看保存的 JSON 文件

```bash
# 查看完整 JSON 文件
cat test_ceph_output.json

# 或使用 Python 格式化查看（更易读）
python -m json.tool test_ceph_output.json

# 或使用提供的查看脚本
python view_json.py
```

### 方法 3: 只查看 CephalometricMeasurements 部分

```bash
# 如果安装了 jq
jq '.data.CephalometricMeasurements' test_ceph_output.json

# 或使用 Python 一行命令
python -c "import json; data=json.load(open('test_ceph_output.json')); print(json.dumps(data['data']['CephalometricMeasurements'], indent=2, ensure_ascii=False))"
```

## 完整示例

```bash
# 1. 获取 taskId（从 Flask 日志或浏览器）
TASK_ID="abc123-def456-ghi789"

# 2. 运行测试脚本
python test_ceph_json.py $TASK_ID

# 3. 查看 JSON 文件
cat test_ceph_output.json

# 或只查看 CephalometricMeasurements 部分
python view_json.py
```

## 预期输出

测试脚本会显示：
- 每个测量项的 Level 值
- Level 值验证结果（✓ 表示正确，✗ 表示错误）
- CephalometricMeasurements 部分的完整 JSON

JSON 文件会保存在: `test_ceph_output.json`

