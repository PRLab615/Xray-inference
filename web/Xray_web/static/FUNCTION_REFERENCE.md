# app.js 函数参考手册

> **文件:** `web/Xray_web/static/app.js`  
> **总函数数:** 60+  
> **最后更新:** 2025-11-23

---

## 目录

1. [初始化和工具函数](#初始化和工具函数)
2. [任务提交和轮询](#任务提交和轮询)
3. [结果展示](#结果展示)
4. [侧位片渲染](#侧位片渲染)
5. [全景片渲染](#全景片渲染)
6. [报告生成](#报告生成)
7. [错误处理和验证](#错误处理和验证)
8. [样式和用户体验](#样式和用户体验)

---

## 初始化和工具函数

### `init()`
**功能:** 初始化函数，绑定所有事件监听器  
**调用时机:** 页面加载完成时  
**代码:**
```javascript
function init() {
    document.getElementById('taskType').addEventListener('change', onTaskTypeOrFileChange);
    document.getElementById('imageFile').addEventListener('change', onTaskTypeOrFileChange);
    document.getElementById('gender').addEventListener('change', onPatientInfoChange);
    document.getElementById('dentalStage').addEventListener('change', onPatientInfoChange);
    document.getElementById('submitBtn').addEventListener('click', onSubmit);
    setupWindowResizeHandler();
    setupKeyboardShortcuts();
    enableSmoothScrolling();
}
```

### `initKonvaStage(containerId, width, height)`
**功能:** 初始化 Konva Stage  
**参数:**
- `containerId` (string): 容器元素 ID
- `width` (number): Stage 宽度
- `height` (number): Stage 高度

**返回:** Konva.Stage 实例  
**示例:**
```javascript
const stage = initKonvaStage('imageContainer', 800, 600);
```

### `scaleCoordinates(x, y, scale)`
**功能:** 坐标缩放转换  
**参数:**
- `x` (number): 原始 X 坐标
- `y` (number): 原始 Y 坐标
- `scale` (number): 缩放比例

**返回:** `{x: number, y: number}`  
**示例:**
```javascript
const scaled = scaleCoordinates(100, 200, 0.5); // {x: 50, y: 100}
```

### `smoothPolyline(points, iterations)`
**功能:** 使用 Chaikin 算法平滑多边形  
**参数:**
- `points` (array): 点数组 `[x1, y1, x2, y2, ...]`
- `iterations` (number): 平滑迭代次数（默认 1）

**返回:** 平滑后的点数组  
**示例:**
```javascript
const smoothed = smoothPolyline([0, 0, 100, 0, 100, 100, 0, 100], 2);
```

### `normalizeMaskPolygons(coords, scale)`
**功能:** 归一化分割坐标为多边形点列  
**参数:**
- `coords` (array): 坐标数据（支持多种格式）
- `scale` (number): 缩放比例

**返回:** 多边形数组  
**支持格式:**
- 矩形: `[x1, y1, x2, y2]`
- 单多边形: `[[x,y], [x,y], ...]`
- 多多边形: `[[[x,y], ...], [[x,y], ...]]`

### `generateUUID()`
**功能:** 生成 UUID v4（兼容性方案）  
**返回:** UUID 字符串  
**示例:**
```javascript
const taskId = generateUUID(); // "550e8400-e29b-41d4-a716-446655440000"
```

---

## 任务提交和轮询

### `onSubmit()`
**功能:** 处理任务提交  
**流程:**
1. 验证文件选择
2. 生成 taskId
3. 构建 FormData
4. 发送到 AI 后端
5. 启动轮询

### `onTaskTypeOrFileChange()`
**功能:** 监听任务类型或文件变化  
**逻辑:** 侧位片图片时显示患者信息表单

### `onPatientInfoChange()`
**功能:** 监听患者信息表单变化  
**逻辑:** 更新提交按钮状态

### `updateSubmitButtonState()`
**功能:** 更新提交按钮的启用/禁用状态  
**规则:** 患者信息表单显示时，必须填写完整才能启用

### `startPolling(taskId)`
**功能:** 启动轮询机制  
**参数:** `taskId` (string): 任务 ID  
**流程:**
1. 记录轮询开始时间
2. 立即执行一次轮询
3. 设置定时器，每 3 秒轮询一次

### `pollResult(taskId)`
**功能:** 单次轮询查询  
**参数:** `taskId` (string): 任务 ID  
**流程:**
1. 检查是否超时（6 分钟）
2. 向 Flask 服务器查询结果
3. 根据响应状态处理

### `stopPolling()`
**功能:** 停止轮询定时器  
**调用时机:** 结果到达或超时时

---

## 结果展示

### `displayResult(resultJson)`
**功能:** 展示分析结果或错误信息  
**参数:** `resultJson` (object): 结果 JSON  
**流程:**
1. 隐藏加载指示器
2. 重置 UI
3. 根据状态进行路由
4. 成功时根据任务类型调用对应渲染函数

### `displayError(error)`
**功能:** 显示错误信息  
**参数:** `error` (object): 错误对象  
**示例:**
```javascript
displayError({ displayMessage: '图片加载失败' });
```

### `clearCanvas()`
**功能:** 清空 Canvas 和 Konva 对象  
**操作:**
- 销毁所有图层
- 销毁 Stage 实例
- 重置全局状态

### `clearReport()`
**功能:** 清空报告容器  
**操作:** 设置 `reportContainer.innerHTML = ''`

### `showLoading()`
**功能:** 显示加载图标  
**操作:** 移除 `loadingIndicator` 的 `hidden` 类

### `hideLoading()`
**功能:** 隐藏加载图标  
**操作:** 添加 `loadingIndicator` 的 `hidden` 类

---

## 侧位片渲染

### `renderCephalometric(data)`
**功能:** 渲染侧位片结果  
**参数:** `data` (object): 侧位片分析数据  
**流程:**
1. 显示主容器
2. 生成报告
3. 加载图片
4. 初始化 Konva Stage
5. 绘制背景图和关键点

### `drawLandmarks(data, stage, scale)`
**功能:** 绘制关键点  
**参数:**
- `data` (object): 侧位片数据
- `stage` (Konva.Stage): Konva Stage 实例
- `scale` (number): 缩放比例

**绘制内容:**
- 红色圆点表示检测到的关键点
- 灰色空心圆表示缺失的关键点
- 白色文本标签显示关键点标签

### `showLandmarkTooltip(node, landmark, event)`
**功能:** 显示关键点 Tooltip  
**参数:**
- `node` (Konva.Node): Konva 节点
- `landmark` (object): 关键点数据
- `event` (object): Konva 事件对象

**显示内容:**
- 关键点全名
- 标签
- 坐标
- 置信度

---

## 全景片渲染

### `renderPanoramic(data)`
**功能:** 渲染全景片结果  
**参数:** `data` (object): 全景片分析数据  
**流程:**
1. 显示主容器
2. 生成报告
3. 加载图片
4. 初始化 Konva Stage
5. 绘制背景图、牙齿分割、区域性发现

### `drawToothSegments(data, stage, scale)`
**功能:** 绘制牙齿分割区域  
**参数:**
- `data` (object): 全景片数据
- `stage` (Konva.Stage): Konva Stage 实例
- `scale` (number): 缩放比例

**绘制内容:**
- 绿色多边形轮廓表示牙齿分割区域
- 使用 Chaikin 算法平滑

### `drawRegionalFindings(data, stage, scale)`
**功能:** 绘制区域性发现  
**参数:**
- `data` (object): 全景片数据
- `stage` (Konva.Stage): Konva Stage 实例
- `scale` (number): 缩放比例

**绘制内容:**
- 蓝色矩形：种植体
- 黄色虚线矩形：根尖密度影
- 紫色/绿色/橙色多边形：髁突

### `showToothTooltip(node, toothData, event)`
**功能:** 显示牙齿 Tooltip  
**显示内容:**
- 牙位 FDI
- 属性类发现列表
- 置信度

### `showFindingTooltip(node, findingData, event)`
**功能:** 显示区域性发现 Tooltip  
**显示内容:**
- 发现类型（种植体/密度影）
- 详细描述
- 置信度

### `showCondyleTooltip(node, condyleInfo, side, event)`
**功能:** 显示髁突 Tooltip  
**显示内容:**
- 侧别（左/右）
- 形态（正常/吸收）
- 详细描述
- 置信度

### `hideTooltip()`
**功能:** 隐藏所有 Tooltip  
**操作:** 移除所有 Tooltip 元素

---

## 报告生成

### `buildCephReport(data)`
**功能:** 构建侧位片结构化报告  
**参数:** `data` (object): 侧位片分析数据  
**报告内容:**
1. 分析摘要
2. 骨骼分析
3. 牙齿分析
4. 生长发育评估
5. 气道分析
6. JSON 数据

### `buildPanoReport(data)`
**功能:** 构建全景片结构化报告  
**参数:** `data` (object): 全景片分析数据  
**报告内容:**
1. 整体诊断摘要
2. 颌骨与关节
3. 牙周与缺牙
4. 智齿分析
5. 特殊发现
6. 单牙诊断详情
7. JSON 数据

### `createReportSection(title)`
**功能:** 创建报告区块  
**参数:** `title` (string): 区块标题  
**返回:** HTMLElement

### `createKeyValue(key, value)`
**功能:** 创建键值对元素  
**参数:**
- `key` (string): 键名
- `value` (string|number): 值

**返回:** HTMLElement

### `createMeasurementItem(measurement)`
**功能:** 创建测量项元素  
**参数:** `measurement` (object): 测量项数据  
**返回:** HTMLElement

### `createToothCard(tooth)`
**功能:** 创建单牙诊断卡片  
**参数:** `tooth` (object): 牙齿数据  
**返回:** HTMLElement

### `getMeasurementLabel(label)`
**功能:** 获取测量项标签（中文名称）  
**参数:** `label` (string): 测量项标签  
**返回:** 中文名称

### `getMeasurementConclusion(label, level)`
**功能:** 获取测量项诊断结论  
**参数:**
- `label` (string): 测量项标签
- `level` (number|boolean|array): 等级

**返回:** 诊断结论文本

### `isBoneMeasurement(label)`
**功能:** 判断是否为骨骼测量项  
**参数:** `label` (string): 测量项标签  
**返回:** boolean

### `isToothMeasurement(label)`
**功能:** 判断是否为牙齿测量项  
**参数:** `label` (string): 测量项标签  
**返回:** boolean

### `formatPeriodontalLevel(level)`
**功能:** 格式化牙周吸收等级  
**参数:** `level` (number): 等级 (0/1/2/3)  
**返回:** 等级文本

### `formatWisdomLevel(level)`
**功能:** 格式化智齿等级  
**参数:** `level` (number): 等级 (1-4)  
**返回:** 等级文本

---

## 错误处理和验证

### `resetUI()`
**功能:** 完善的 UI 重置函数  
**操作:**
1. 清空 Canvas
2. 清空报告
3. 隐藏主容器
4. 隐藏错误提示
5. 隐藏加载指示器
6. 重置全局状态
7. 重新启用提交按钮

### `handleImageLoadError(errorMsg)`
**功能:** 处理图片加载失败  
**参数:** `errorMsg` (string): 错误信息  
**操作:** 显示错误提示

### `safeGet(obj, path, defaultValue)`
**功能:** 安全地访问嵌套对象属性  
**参数:**
- `obj` (object): 对象
- `path` (string): 属性路径（如 'a.b.c'）
- `defaultValue` (*): 默认值

**返回:** 属性值或默认值  
**示例:**
```javascript
const landmarks = safeGet(data, 'LandmarkPositions.Landmarks', []);
```

### `isValidCoordinate(x, y)`
**功能:** 验证坐标数据的有效性  
**参数:**
- `x` (number): X 坐标
- `y` (number): Y 坐标

**返回:** boolean  
**检查:**
- 是否为数字
- 是否为有限数字
- 是否不为 NaN

### `isValidCoordinateArray(coords)`
**功能:** 验证数组坐标的有效性  
**参数:** `coords` (array): 坐标数组  
**返回:** boolean  
**支持格式:**
- `[[x,y], [x,y], ...]`
- `[x1, y1, x2, y2, ...]`

### `validateResultData(resultJson)`
**功能:** 验证结果数据的完整性  
**参数:** `resultJson` (object): 结果 JSON  
**返回:** `{valid: boolean, error?: string}`  
**检查:**
- 结果对象是否存在
- status 字段是否存在
- 成功时 data 字段是否存在
- 失败时 error 字段是否存在

### `recalculateCoordinatesOnResize(originalX, originalY, oldScale, newScale)`
**功能:** 处理响应式缩放时重新计算坐标  
**参数:**
- `originalX` (number): 原始 X 坐标
- `originalY` (number): 原始 Y 坐标
- `oldScale` (number): 旧缩放比例
- `newScale` (number): 新缩放比例

**返回:** `{x: number, y: number}`

### `setupWindowResizeHandler()`
**功能:** 处理窗口大小变化  
**特性:**
- 防抖机制（300ms）
- 自动调整 Canvas 尺寸
- 自动重新绘制

---

## 样式和用户体验

### `createEnhancedTooltip(content, position)`
**功能:** 创建增强的 Tooltip  
**参数:**
- `content` (string): HTML 内容
- `position` (object): 位置 `{x, y}`

**返回:** HTMLElement  
**特性:**
- 淡入动画
- 自动位置调整
- 阴影效果

### `showImageLoadingPlaceholder()`
**功能:** 显示图像加载占位符  
**操作:** 在容器中显示加载动画和文本

### `removeImageLoadingPlaceholder()`
**功能:** 移除加载占位符  
**操作:** 删除占位符元素

### `addReportSectionAnimations()`
**功能:** 为报告区块添加淡入上升动画  
**特性:** 错开动画（每个区块延迟 50ms）

### `enableSmoothScrolling()`
**功能:** 启用报告区域的平滑滚动  
**操作:** 设置 `scroll-behavior: smooth`

### `setupKeyboardShortcuts()`
**功能:** 设置键盘快捷键  
**快捷键:**
- **ESC**: 隐藏 Tooltip
- **R**: 重置 UI（可选）

### `displayErrorWithAutoClose(error, autoCloseTime)`
**功能:** 显示错误提示并自动关闭  
**参数:**
- `error` (object): 错误对象
- `autoCloseTime` (number): 自动关闭时间（毫秒，默认 5000）

### `addReportCardHoverEffects()`
**功能:** 为报告卡片添加悬停效果  
**效果:**
- 向右移动 4px
- 显示阴影

---

## 全局状态对象

```javascript
const appState = {
    currentTaskId: null,       // 当前任务ID
    currentTaskType: null,     // 当前任务类型
    pollingTimer: null,        // 轮询定时器
    pollingStartTime: null,    // 轮询开始时间
    cachedResult: null,        // 缓存的结果JSON
    konvaStage: null,          // Konva Stage 实例
    konvaLayers: {},           // 图层对象集合
    originalImage: null,       // 原始图片对象
    imageScale: 1.0            // 图片缩放比例
};
```

---

## 全局配置常量

```javascript
const CONFIG = {
    AI_BACKEND_URL: 'http://192.168.1.17:18000/api/v1/analyze',
    CALLBACK_URL: 'http://192.168.1.17:5000/callback',
    POLL_INTERVAL: 3000,       // 3秒
    POLL_TIMEOUT: 360000       // 6分钟
};
```

---

## 关键点全名映射表

```javascript
const LANDMARK_FULL_NAMES = {
    'S': '蝶鞍点',
    'N': '鼻根点',
    'Ba': '颅底点',
    // ... 共 25+ 个关键点
};
```

---

## 使用示例

### 示例 1：提交侧位片任务
```javascript
// 用户选择侧位片图片和患者信息后，点击提交按钮
// onSubmit() 会自动调用
```

### 示例 2：手动重置 UI
```javascript
resetUI(); // 清空所有状态和显示
```

### 示例 3：验证坐标
```javascript
if (isValidCoordinate(landmark.X, landmark.Y)) {
    // 绘制关键点
}
```

### 示例 4：安全访问数据
```javascript
const landmarks = safeGet(data, 'LandmarkPositions.Landmarks', []);
landmarks.forEach(landmark => {
    // 处理关键点
});
```

### 示例 5：显示增强 Tooltip
```javascript
const tooltip = createEnhancedTooltip(
    '<strong>关键点</strong><br>坐标: (100, 200)',
    { x: 150, y: 250 }
);
```

---

**文档版本:** 1.0  
**最后更新:** 2025-11-23  
**总函数数:** 60+

