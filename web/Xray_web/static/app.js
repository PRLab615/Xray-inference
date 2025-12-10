/**
 * AI 异步分析前端核心逻辑
 * 实现任务提交、轮询、结果展示和状态管理
 */

// 兼容性工具函数：生成 UUID v4
function generateUUID() {
    // 优先使用原生 API（如果可用）
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
        return crypto.randomUUID();
    }
    
    // 降级方案：使用 Math.random() 生成 UUID v4
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// 全局状态对象
const appState = {
    currentTaskId: null,       // 当前任务ID
    currentTaskType: null,     // 当前任务类型 (panoramic/cephalometric)
    pollingTimer: null,        // 轮询定时器
    pollingStartTime: null,    // 轮询开始时间
    cachedResult: null,        // 缓存的结果JSON
    konvaStage: null,          // Konva Stage 实例
    konvaLayers: {},           // 图层对象集合
    originalImage: null,       // 原始图片对象
    imageScale: 1.0,           // 图片缩放比例
    layerVisibility: {},       // 图层显示状态 {layerKey: true/false}
    currentFile: null,         // 当前选择的文件对象
    cephLandmarks: {},         // 侧位片点位映射（Label -> [x,y]）
    cephMeasurements: [],      // 侧位片测量项列表
    activeMeasurementLabel: null // 当前高亮的测量项
};

// 动态获取当前主机名，支持在任意 IP 的机器上运行
const CURRENT_HOST = window.location.hostname || 'localhost';

// 侧位片短标签到完整名称映射（用于兼容 Visualization 的短标签）
const SHORT_LABEL_MAP = {
    S: 'Sella',
    N: 'Nasion',
    Or: 'Orbitale',
    Po: 'Porion',
    A: 'Subspinale',
    B: 'Supramentale',
    Pog: 'Pogonion',
    Me: 'Menton',
    Gn: 'Gnathion',
    Go: 'Gonion',
    L1: 'Incision inferius',
    UI: 'Incision superius',
    U1: 'Incision superius',
    PNS: 'Posterior nasal spine',
    ANS: 'Anterior nasal spine',
    Ar: 'Articulare',
    Ba: 'Ba',
    Bo: 'Bo',
    Pt: 'Pt',
    PTM: 'PTM',
    Co: 'Co',
    U1A: 'U1A',
    L1A: 'L1A',
    U6: 'U6',
    L6: 'L6',
    Pcd: 'Pcd'
};

// 全局配置常量
const CONFIG = {
    // 动态构建 API 地址，使用当前访问的主机名
    AI_BACKEND_SYNC_URL: `http://${CURRENT_HOST}:18000/api/v1/analyze`,      // 同步/伪同步接口
    AI_BACKEND_ASYNC_URL: `http://${CURRENT_HOST}:18000/api/v1/analyze_async`, // 纯异步接口
    FLASK_UPLOAD_URL: `http://${CURRENT_HOST}:5000/upload`,  // Flask 服务器上传接口
    CALLBACK_URL: `http://${CURRENT_HOST}:5000/callback`,
    POLL_INTERVAL: 3000,       // 3秒
    POLL_TIMEOUT: 360000,      // 6分钟
    STROKE_WIDTH: 0.7            // 统一线条宽度（像素）
};

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    init();
});

/**
 * 初始化函数：绑定所有事件监听器
 */
function init() {
    // 绑定任务类型和文件选择的变化事件
    document.getElementById('taskType').addEventListener('change', onTaskTypeOrFileChange);
    document.getElementById('imageFile').addEventListener('change', onTaskTypeOrFileChange);
    
    // 绑定患者信息表单的变化事件
    document.getElementById('gender').addEventListener('change', onPatientInfoChange);
    document.getElementById('dentalStage').addEventListener('change', onPatientInfoChange);
    
    // 绑定提交按钮
    document.getElementById('submitBtn').addEventListener('click', onSubmit);
    
    // 绑定标签页切换
    const tabButtons = document.querySelectorAll('.tab-btn');
    tabButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            const tabName = this.getAttribute('data-tab');
            switchTab(tabName);
        });
    });
    // 默认展示 AI 分析
    switchTab('aiTab');
    
    // 绑定手动可视化按钮
    const manualBtn = document.getElementById('manualVisualizeBtn');
    if (manualBtn) {
        manualBtn.addEventListener('click', onManualVisualize);
    }
    
    // 测量可视化控制
    const prevBtn = document.getElementById('prevMeasurement');
    const nextBtn = document.getElementById('nextMeasurement');
    const clearBtn = document.getElementById('clearMeasurement');
    if (prevBtn) prevBtn.addEventListener('click', () => jumpMeasurement(-1));
    if (nextBtn) nextBtn.addEventListener('click', () => jumpMeasurement(1));
    if (clearBtn) clearBtn.addEventListener('click', clearMeasurementVisualization);
    
    // 步骤14：设置窗口大小变化处理
    setupWindowResizeHandler();
    
    // 步骤15：设置键盘快捷键和平滑滚动
    setupKeyboardShortcuts();
    enableSmoothScrolling();
    
    console.log('前端初始化完成');
}

/**
 * 监听任务类型或文件变化，动态显示/隐藏 patientInfo 表单
 * 核心逻辑：
 * - 如果 taskType == 'cephalometric' 且文件为图片，显示患者信息表单
 * - 其他情况隐藏患者信息表单
 */
function onTaskTypeOrFileChange() {
    const taskType = document.getElementById('taskType').value;
    const fileInput = document.getElementById('imageFile');
    const file = fileInput.files[0];
    const patientInfoSection = document.getElementById('patientInfoSection');
    const submitBtn = document.getElementById('submitBtn');
    
    // 保存当前文件到 appState
    appState.currentFile = file || null;
    
    // 判断是否需要显示患者信息表单
    let shouldShowPatientInfo = false;
    
    if (taskType === 'cephalometric' && file) {
        const fileName = file.name.toLowerCase();
        // 检查是否为图片文件（.jpg, .jpeg, .png）
        const isImage = fileName.endsWith('.jpg') || 
                       fileName.endsWith('.jpeg') || 
                       fileName.endsWith('.png');
        shouldShowPatientInfo = isImage;
    }
    
    // 更新 UI：显示或隐藏患者信息表单
    if (shouldShowPatientInfo) {
        patientInfoSection.classList.remove('hidden');
        // 患者信息表单显示时，需要检查是否填写完整
        updateSubmitButtonState();
    } else {
        patientInfoSection.classList.add('hidden');
        // 患者信息表单隐藏时，提交按钮可用（前提是已选择文件）
        if (file) {
            submitBtn.disabled = false;
        } else {
            submitBtn.disabled = false; // 即使未选择文件，也不禁用，由提交时检查
        }
    }
    
    console.log(`动态表单逻辑: taskType=${taskType}, 文件=${file ? file.name : '未选择'}, 显示患者信息=${shouldShowPatientInfo}`);
}

/**
 * 监听患者信息表单的变化，更新提交按钮状态
 */
function onPatientInfoChange() {
    updateSubmitButtonState();
}

/**
 * 更新提交按钮的启用/禁用状态
 * 规则：如果患者信息表单显示，必须填写完整才能启用提交按钮
 */
function updateSubmitButtonState() {
    const patientInfoSection = document.getElementById('patientInfoSection');
    const submitBtn = document.getElementById('submitBtn');
    
    // 如果患者信息表单显示，检查是否填写完整
    if (!patientInfoSection.classList.contains('hidden')) {
        const gender = document.getElementById('gender').value;
        const dentalStage = document.getElementById('dentalStage').value;
        
        // 只有性别和牙期都填写了才启用提交按钮
        submitBtn.disabled = !(gender && dentalStage);
        
        console.log(`提交按钮状态: gender=${gender}, dentalStage=${dentalStage}, enabled=${!submitBtn.disabled}`);
    }
}

/**
 * 显示加载图标
 */
function showLoading() {
    document.getElementById('loadingIndicator').classList.remove('hidden');
}

/**
 * 隐藏加载图标
 */
function hideLoading() {
    document.getElementById('loadingIndicator').classList.add('hidden');
}

/**
 * 显示成功提示消息
 * @param {string} message - 提示消息
 * @param {number} duration - 显示时长（毫秒），默认 3000
 */
function showSuccessMessage(message, duration = 3000) {
    // 创建提示元素
    const toast = document.createElement('div');
    toast.className = 'success-toast';
    toast.textContent = message;
    
    // 添加到页面
    document.body.appendChild(toast);
    
    // 触发动画
    setTimeout(() => {
        toast.classList.add('show');
    }, 10);
    
    // 自动隐藏
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => {
            document.body.removeChild(toast);
        }, 300); // 等待动画完成
    }, duration);
}

// ============================================
// Konva Stage 初始化和工具函数
// ============================================

/**
 * 初始化 Konva Stage
 * @param {string} containerId - 容器元素 ID
 * @param {number} width - Stage 宽度
 * @param {number} height - Stage 高度
 * @returns {Konva.Stage} Stage 实例
 */
function initKonvaStage(containerId, width, height) {
    const container = document.getElementById(containerId);
    if (!container) {
        console.error('容器元素不存在:', containerId);
        return null;
    }
    
    // 如果已存在 Stage，先销毁
    if (appState.konvaStage) {
        appState.konvaStage.destroy();
        appState.konvaStage = null;
    }
    
    // 确保尺寸有效
    if (width <= 0 || height <= 0) {
        console.error('无效的 Stage 尺寸:', width, 'x', height);
        return null;
    }
    
    // 创建新的 Stage
    const stage = new Konva.Stage({
        container: containerId,
        width: width,
        height: height
    });
    
    appState.konvaStage = stage;
    appState.konvaLayers = {};
    
    console.log('Konva Stage 初始化完成:', width, 'x', height);
    return stage;
}

/**
 * 坐标缩放转换
 * @param {number} x - 原始 X 坐标
 * @param {number} y - 原始 Y 坐标
 * @param {number} scale - 缩放比例
 * @returns {{x: number, y: number}} 转换后的坐标
 */
function scaleCoordinates(x, y, scale) {
    return {
        x: x * scale,
        y: y * scale
    };
}

/**
 * 构建点位映射：Label -> [x, y]
 * 仅保留已检测且坐标有效的点
 */
function buildLandmarkMap(data) {
    const map = {};
    const landmarks = data?.LandmarkPositions?.Landmarks || [];
    landmarks.forEach(l => {
        if (l && l.Status === 'Detected' && l.X != null && l.Y != null) {
            // 原始全名
            map[l.Label] = [l.X, l.Y];
            // 尝试匹配短标签
            const shortKey = Object.keys(SHORT_LABEL_MAP).find(k => SHORT_LABEL_MAP[k] === l.Label);
            if (shortKey) {
                map[shortKey] = [l.X, l.Y];
            }
        }
    });
    return map;
}

/**
 * 确保指定图层存在，不存在则创建
 */
function ensureLayer(layerKey) {
    if (!appState.konvaStage) return null;
    // 如果层已存在，直接返回（renderCephalometric 已按正确顺序创建）
    if (appState.konvaLayers[layerKey]) return appState.konvaLayers[layerKey];
    // 如果层不存在，创建并添加到 stage
    // 注意：对于 measurementLines，应该在 renderCephalometric 中已创建，这里不应该执行
    const layer = new Konva.Layer();
    appState.konvaStage.add(layer);
    appState.konvaLayers[layerKey] = layer;
    return layer;
}

/**
 * 设置当前激活的测量项并高亮
 */
function setActiveMeasurementLabel(label) {
    appState.activeMeasurementLabel = label || null;
    const items = document.querySelectorAll('.measurement-item');
    items.forEach(node => {
        if (label && node.dataset && node.dataset.label === label) {
            node.classList.add('active');
        } else {
            node.classList.remove('active');
        }
    });
}

/**
 * 清空测量线
 */
function clearMeasurementVisualization() {
    const layer = appState.konvaLayers.measurementLines;
    if (layer) {
        layer.destroyChildren();
        layer.draw();
    }
    appState.activeMeasurementLabel = null;
    setActiveMeasurementLabel(null);
    initLayerControlPanel();
}

/**
 * 按增量切换测量项（仅包含可视化）
 */
function jumpMeasurement(delta) {
    const list = getNavigableMeasurements();
    if (!list.length) {
        alert('无可视化的测量项');
        return;
    }
    const currentIndex = list.findIndex(m => m.Label === appState.activeMeasurementLabel);
    let nextIndex = currentIndex + delta;
    if (nextIndex >= list.length) nextIndex = 0;
    if (nextIndex < 0) nextIndex = list.length - 1;
    const target = list[nextIndex];
    handleMeasurementClick(target);
}

/**
 * 获取可导航的测量项列表（含 Visualization）
 */
function getNavigableMeasurements() {
    if (!Array.isArray(appState.cephMeasurements)) return [];
    return appState.cephMeasurements.filter(m => m && m.Visualization);
}

/**
 * 渲染单个测量项的可视化（线段）
 */
function renderMeasurementVisualization(measurement) {
    if (!measurement || !measurement.Visualization) {
        console.warn('该测量项无可视化指令');
        return;
    }
    if (!appState.konvaStage) {
        console.warn('Konva Stage 未初始化，无法绘制可视化');
        return;
    }

    const layer = ensureLayer('measurementLines');
    if (!layer) return;
    layer.destroyChildren();

    const vis = measurement.Visualization;
    const pointMap = { ...appState.cephLandmarks };
    if (vis.VirtualPoints && typeof vis.VirtualPoints === 'object') {
        Object.entries(vis.VirtualPoints).forEach(([k, v]) => {
            if (Array.isArray(v) && v.length >= 2) {
                pointMap[k] = v;
            }
        });
    }

    const scale = appState.imageScale || 1;
    const elements = Array.isArray(vis.Elements) ? vis.Elements : [];
    let drawCount = 0;

    elements.forEach(el => {
        if (!el || el.Type !== 'Line') return;
        const from = pointMap[el.From];
        const to = pointMap[el.To];
        if (!from || !to) return;

        const role = el.Role === 'Measurement' ? 'Measurement' : 'Reference';
        const style = el.Style === 'Dashed' ? [6, 4] : [];
        const stroke = role === 'Measurement' ? '#e74c3c' : '#3498db';
        const strokeWidth = role === 'Measurement' ? 2 : 1;

        const line = new Konva.Line({
            points: [from[0] * scale, from[1] * scale, to[0] * scale, to[1] * scale],
            stroke,
            strokeWidth,
            dash: style,
            lineCap: 'round',
            lineJoin: 'round',
            listening: false
        });
        layer.add(line);
        drawCount++;
    });

    layer.draw();
    appState.konvaStage.draw();
    appState.konvaLayers.measurementLines = layer;
    appState.layerVisibility.measurementLines = true;
    initLayerControlPanel();

    if (drawCount === 0) {
        console.warn('可视化元素为空或坐标缺失，未绘制任何线段');
    }

    // 显示测量工具栏
    const tools = document.getElementById('measurementTools');
    if (tools) {
        tools.classList.remove('hidden');
    }
}

/**
 * 处理测量项点击事件
 */
function handleMeasurementClick(measurement) {
    if (!measurement) return;
    if (!measurement.Visualization) {
        alert('该测量项暂无可视化');
        return;
    }
    setActiveMeasurementLabel(measurement.Label);
    renderMeasurementVisualization(measurement);
}

/**
 * 渲染所有测量项的可视化（叠加显示）
 */
function renderAllMeasurements() {
    const measurements = getNavigableMeasurements();
    if (measurements.length === 0) {
        alert('没有可显示的测量线');
        return;
    }
    
    if (!appState.konvaStage) {
        console.warn('Konva Stage 未初始化，无法绘制可视化');
        return;
    }
    
    const layer = ensureLayer('measurementLines');
    if (!layer) return;
    layer.destroyChildren();
    
    const scale = appState.imageScale || 1;
    let totalDrawCount = 0;
    
    measurements.forEach(measurement => {
        if (!measurement || !measurement.Visualization) return;
        
        const vis = measurement.Visualization;
        const pointMap = { ...appState.cephLandmarks };
        if (vis.VirtualPoints && typeof vis.VirtualPoints === 'object') {
            Object.entries(vis.VirtualPoints).forEach(([k, v]) => {
                if (Array.isArray(v) && v.length >= 2) {
                    pointMap[k] = v;
                }
            });
        }
        
        const elements = Array.isArray(vis.Elements) ? vis.Elements : [];
        elements.forEach(el => {
            if (!el || el.Type !== 'Line') return;
            const from = pointMap[el.From];
            const to = pointMap[el.To];
            if (!from || !to) return;
            
            const role = el.Role === 'Measurement' ? 'Measurement' : 'Reference';
            const style = el.Style === 'Dashed' ? [6, 4] : [];
            const stroke = role === 'Measurement' ? '#e74c3c' : '#3498db';
            const strokeWidth = role === 'Measurement' ? 2 : 1;
            
            const line = new Konva.Line({
                points: [from[0] * scale, from[1] * scale, to[0] * scale, to[1] * scale],
                stroke,
                strokeWidth,
                dash: style,
                lineCap: 'round',
                lineJoin: 'round',
                listening: false
            });
            layer.add(line);
            totalDrawCount++;
        });
    });
    
    layer.draw();
    appState.konvaStage.draw();
    appState.konvaLayers.measurementLines = layer;
    appState.layerVisibility.measurementLines = true;
    appState.activeMeasurementLabel = null;
    initLayerControlPanel();
    
    if (totalDrawCount === 0) {
        console.warn('未绘制任何线段');
    } else {
        console.log(`已绘制所有测量线，共 ${totalDrawCount} 条线段`);
    }
    
    const tools = document.getElementById('measurementTools');
    if (tools) {
        tools.classList.remove('hidden');
    }
}

/**
 * 计算两点距离平方
 */
function getSqDist(p1, p2) {
    var dx = p1.x - p2.x,
        dy = p1.y - p2.y;
    return dx * dx + dy * dy;
}

/**
 * 计算点到线段的垂直距离平方
 */
function getSqSegDist(p, p1, p2) {
    var x = p1.x,
        y = p1.y,
        dx = p2.x - x,
        dy = p2.y - y;

    if (dx !== 0 || dy !== 0) {
        var t = ((p.x - x) * dx + (p.y - y) * dy) / (dx * dx + dy * dy);
        if (t > 1) {
            x = p2.x;
            y = p2.y;
        } else if (t > 0) {
            x += dx * t;
            y += dy * t;
        }
    }

    dx = p.x - x;
    dy = p.y - y;

    return dx * dx + dy * dy;
}

/**
 * 简化点集 (Ramer-Douglas-Peucker 算法)
 * @param {Array} points - [{x,y}, {x,y}...] 或 [x,y,x,y...]
 * @param {Number} tolerance - 容差 (像素单位，例如 1.5 ~ 2.5)
 * @param {Boolean} isFlat - 输入是否为扁平数组 [x,y,x,y...]
 * @return {Array} 简化后的数组
 */
function simplifyPoints(points, tolerance = 1, isFlat = true) {
    if (points.length <= 2) return points;

    // 1. 统一格式转换为对象数组 [{x,y}...]
    let srcPoints = [];
    if (isFlat) {
        for (let i = 0; i < points.length; i += 2) {
            srcPoints.push({ x: points[i], y: points[i + 1] });
        }
    } else {
        srcPoints = points;
    }

    // RDP 核心逻辑
    const sqTolerance = tolerance * tolerance;
    
    function simplifyDPStep(points, first, last, sqTolerance, simplified) {
        var maxSqDist = sqTolerance,
            index = first;

        for (var i = first + 1; i < last; i++) {
            var sqDist = getSqSegDist(points[i], points[first], points[last]);
            if (sqDist > maxSqDist) {
                index = i;
                maxSqDist = sqDist;
            }
        }

        if (maxSqDist > sqTolerance) {
            if (index - first > 1) simplifyDPStep(points, first, index, sqTolerance, simplified);
            simplified.push(points[index]);
            if (last - index > 1) simplifyDPStep(points, index, last, sqTolerance, simplified);
        }
    }

    var simplified = [srcPoints[0]];
    simplifyDPStep(srcPoints, 0, srcPoints.length - 1, sqTolerance, simplified);
    simplified.push(srcPoints[srcPoints.length - 1]);

    // 2. 转回扁平数组 [x,y,x,y...] 以供 Konva 使用
    if (isFlat) {
        const res = [];
        for (let i = 0; i < simplified.length; i++) {
            res.push(simplified[i].x, simplified[i].y);
        }
        return res;
    }
    return simplified;
}

/**
 * 滑动平均平滑 (去除突兀的毛刺)
 * @param {Array} points - 扁平数组 [x,y, x,y, ...]
 * @param {Number} windowSize - 窗口大小 (奇数，建议 3 或 5)。值越大越平滑，但细节丢失越多。
 * @return {Array} 平滑后的数组
 */
function movingAverageSmooth(points, windowSize = 3) {
    if (points.length < 6) return points; // 点太少不处理
    
    const len = points.length / 2; // 点的数量
    const res = [];
    const offset = Math.floor(windowSize / 2);

    for (let i = 0; i < len; i++) {
        let sumX = 0;
        let sumY = 0;

        // 计算窗口内的平均值
        for (let j = -offset; j <= offset; j++) {
            // 处理闭合轮廓的索引越界 (循环取点)
            let idx = (i + j + len) % len; 
            sumX += points[idx * 2];
            sumY += points[idx * 2 + 1];
        }

        res.push(sumX / windowSize, sumY / windowSize);
    }

    return res;
}

// 平滑折线：Chaikin 算法（支持闭合多边形）
// points: [x1, y1, x2, y2, ...]
// iterations: 平滑迭代次数，建议 1-3
function smoothPolyline(points, iterations = 1) {
    if (!Array.isArray(points) || points.length < 6) return points;
    // 转换为二维点数组
    let pts = [];
    for (let i = 0; i < points.length; i += 2) {
        pts.push([points[i], points[i + 1]]);
    }
    const chaikin = (arr) => {
        const res = [];
        const n = arr.length;
        for (let i = 0; i < n; i++) {
            const p0 = arr[i];
            const p1 = arr[(i + 1) % n];
            const Q = [0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]];
            const R = [0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]];
            res.push(Q, R);
        }
        return res;
    };
    for (let k = 0; k < iterations; k++) {
        pts = chaikin(pts);
    }
    // 展平
    const out = [];
    for (let i = 0; i < pts.length; i++) {
        out.push(pts[i][0], pts[i][1]);
    }
    return out;
}

// 归一化分割坐标为一个或多个多边形点列（已缩放）
// 支持三种格式：
// 1) [[x,y], [x,y], ...]
// 2) 多个多边形： [ [[x,y],...], [[x,y],...] ]
// 3) 矩形: [x1, y1, x2, y2]
function normalizeMaskPolygons(coords, scale) {
    if (!coords) return [];
    const polys = [];
    // 矩形
    if (Array.isArray(coords) && coords.length === 4 && coords.every(v => typeof v === 'number')) {
        const [x1, y1, x2, y2] = coords;
        const p = [
            x1 * scale, y1 * scale,
            x2 * scale, y1 * scale,
            x2 * scale, y2 * scale,
            x1 * scale, y2 * scale
        ];
        polys.push(p);
        return polys;
    }
    // 单多边形 [[x,y], ...]
    if (Array.isArray(coords) && Array.isArray(coords[0]) && typeof coords[0][0] === 'number') {
        // 也可能是多多边形
        if (Array.isArray(coords[0][0])) {
            // 多个多边形
            coords.forEach(poly => {
                if (Array.isArray(poly)) {
                    const p = [];
                    poly.forEach(pt => { if (Array.isArray(pt) && pt.length >= 2) { p.push(pt[0] * scale, pt[1] * scale); }});
                    if (p.length >= 6) polys.push(p);
                }
            });
        } else {
            // 单个多边形
            const p = [];
            coords.forEach(pt => { if (Array.isArray(pt) && pt.length >= 2) { p.push(pt[0] * scale, pt[1] * scale); }});
            if (p.length >= 6) polys.push(p);
        }
        return polys;
    }
    return [];
}

// ============================================
// 步骤5：任务提交逻辑（不含轮询）
// ============================================

/**
 * 处理任务提交（v3 JSON 协议）
 * 功能：
 * 1. 先上传文件到 Flask Web 服务器，获取 URL
 * 2. 生成 UUID 作为 taskId
 * 3. 构建 JSON 请求体：
 *    - 图片文件：使用 imageUrl 字段
 *    - DICOM 文件：使用 dicomUrl 字段（后端从 DICOM 解析患者信息）
 * 4. 如果是图片且需要患者信息，添加 patientInfo 字段
 * 5. 发送 POST 请求到 AI 后端（JSON 格式）
 * 6. 处理响应：202 成功、4xx 错误、网络错误
 */
async function onSubmit() {
    const fileInput = document.getElementById('imageFile');
    const file = fileInput.files[0];
    
    // 校验：必须选择文件
    if (!file) {
        alert('请先选择文件');
        return;
    }
    
    // 禁用提交按钮，防止重复提交
    const submitBtn = document.getElementById('submitBtn');
    submitBtn.disabled = true;
    
    // 获取处理模式
    const syncMode = document.querySelector('input[name="syncMode"]:checked').value;
    const isSync = syncMode === 'sync';
    
    console.log('文件类型: 图片');
    
    try {
        // 优先检测示例水印/文件：若命中则直接走本地 JSON，跳过后端
        const demoHit = await detectDemoPanoramicCase(file);
        if (demoHit) {
            console.log(`检测到示例文件：${demoHit.key}，直接加载本地 JSON`);
            clearCanvas();
            clearReport();
            // 2s 延时，避免过快
            await new Promise(res => setTimeout(res, 2000));
            // 读取本地 JSON
            const resp = await fetch(demoHit.json);
            if (!resp.ok) {
                throw new Error(`示例 JSON 加载失败: ${resp.status}`);
            }
            const data = await resp.json();
            appState.currentTaskType = 'panoramic';
            appState.cachedResult = { taskType: 'panoramic', data };
            appState.activeMeasurementLabel = null;
            // 直接渲染（使用当前上传的文件作为显示图）
            renderPanoramic(data);
            submitBtn.disabled = false;
            return;
        }

        // 步骤1：先上传文件到 Flask Web 服务器，获取 URL
        console.log('步骤1：上传文件到 Flask Web 服务器...');
        const uploadFormData = new FormData();
        uploadFormData.append('file', file);
        
        const uploadResponse = await fetch(CONFIG.FLASK_UPLOAD_URL, {
            method: 'POST',
            body: uploadFormData
        });
        
        if (!uploadResponse.ok) {
            const errorData = await uploadResponse.json();
            const errorMsg = errorData.error || '文件上传失败';
            alert('错误：' + errorMsg);
            console.error('文件上传失败:', errorData);
            submitBtn.disabled = false;
            return;
        }
        
        const uploadResult = await uploadResponse.json();
        const fileUrl = uploadResult.imageUrl;
        console.log('文件上传成功，URL:', fileUrl);
        
        // 步骤2：生成 taskId (UUID v4)
        const taskId = generateUUID();
        console.log('生成任务ID:', taskId);
        
        // 步骤3：构建 JSON 请求体
        const taskType = document.getElementById('taskType').value;
        const requestBody = {
            taskId: taskId,
            taskType: taskType
        };
        
        // 图片文件：使用 imageUrl
        requestBody.imageUrl = fileUrl;
        
        // 如果患者信息表单显示（侧位片图片），添加 patientInfo 字段
        const patientInfoSection = document.getElementById('patientInfoSection');
        if (!patientInfoSection.classList.contains('hidden')) {
            requestBody.patientInfo = {
                gender: document.getElementById('gender').value,
                DentalAgeStage: document.getElementById('dentalStage').value
            };
            console.log('患者信息:', requestBody.patientInfo);
        }
        
        // 添加比例尺信息（如果用户填写了）
        const pixelSpacingX = document.getElementById('pixelSpacingX').value;
        const pixelSpacingY = document.getElementById('pixelSpacingY').value;
        if (pixelSpacingX || pixelSpacingY) {
            requestBody.pixelSpacing = {
                scaleX: pixelSpacingX ? parseFloat(pixelSpacingX) : 0.1,
                scaleY: pixelSpacingY ? parseFloat(pixelSpacingY) : 0.1
            };
            console.log('比例尺信息:', requestBody.pixelSpacing);
        }
        
        // 如果是异步模式，添加 callbackUrl
        if (!isSync) {
            requestBody.callbackUrl = CONFIG.CALLBACK_URL;
        }
        
        // 步骤4：发送 JSON 请求到 AI 后端
        const targetUrl = isSync ? CONFIG.AI_BACKEND_SYNC_URL : CONFIG.AI_BACKEND_ASYNC_URL;
        console.log(`步骤2：发送 JSON 请求到 AI 后端 (${isSync ? '同步' : '异步'}):`, targetUrl);
        console.log('请求体:', requestBody);
        
        // 显示加载中
        showLoading();
        
        const response = await fetch(targetUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        });
        
        if (isSync) {
            // 同步模式处理
            if (response.ok) { // 200 OK
                const responseData = await response.json();
                console.log('同步请求成功:', responseData);
                
                appState.currentTaskId = responseData.taskId || taskId;
                appState.currentTaskType = taskType;
                
                // 直接处理结果
                displayResult(responseData);
            } else {
                hideLoading();
                const errorData = await response.json();
                const errorMsg = errorData.detail?.message || errorData.message || '请求失败';
                alert('错误：' + errorMsg);
                console.error('同步请求失败:', errorData);
                submitBtn.disabled = false;
            }
        } else {
            // 异步模式处理 (原有逻辑)
            if (response.status === 202) {
                // 提交成功 (202 Accepted)
                appState.currentTaskId = taskId;
                appState.currentTaskType = taskType;
                console.log('异步任务提交成功，taskId:', taskId, 'taskType:', appState.currentTaskType);
                
                // 启动轮询
                startPolling(taskId);
            } else {
                hideLoading();
                // 同步验证失败（4xx 错误）
                const errorData = await response.json();
                const errorMsg = errorData.detail?.message || errorData.message || '提交失败';
                alert('错误：' + errorMsg);
                console.error('提交失败:', errorData);
                submitBtn.disabled = false;
            }
        }
    } catch (error) {
        hideLoading();
        // 网络错误
        console.error('网络错误:', error);
        alert('网络连接失败，请检查后重试');
        submitBtn.disabled = false;
    }
}

// ============================================
// 步骤6：轮询逻辑和超时处理
// ============================================

/**
 * 启动轮询机制
 * 功能：
 * 1. 记录轮询开始时间
 * 2. 立即执行一次轮询
 * 3. 设置定时器，每 3 秒轮询一次
 */
function startPolling(taskId) {
    console.log('开始轮询，taskId:', taskId);
    appState.pollingStartTime = Date.now();
    
    // 立即执行一次轮询
    pollResult(taskId);
    
    // 设置定时器，每 3 秒轮询一次
    appState.pollingTimer = setInterval(() => {
        pollResult(taskId);
    }, CONFIG.POLL_INTERVAL);
}

/**
 * 单次轮询查询
 * 功能：
 * 1. 检查是否超时（6 分钟）
 * 2. 向 Flask 服务器查询结果
 * 3. 根据响应状态处理：200 成功、404 未到达、其他错误
 */
async function pollResult(taskId) {
    // 检查是否超时
    const elapsed = Date.now() - appState.pollingStartTime;
    if (elapsed > CONFIG.POLL_TIMEOUT) {
        stopPolling();
        hideLoading();
        alert('任务超时，请重试或联系管理员');
        document.getElementById('submitBtn').disabled = false;
        console.error('任务超时:', taskId);
        return;
    }
    
    console.log(`轮询中... (已等待 ${Math.floor(elapsed / 1000)} 秒)`);
    
    try {
        const response = await fetch(`/get-result?taskId=${taskId}`);
        
        if (response.status === 200) {
            // 结果已到达
            const resultData = await response.json();
            console.log('收到结果:', resultData);
            
            // 停止轮询
            stopPolling();
            
            // 缓存结果
            appState.cachedResult = resultData;
            
            // 显示结果（步骤7实现）
            displayResult(resultData);
        } else if (response.status === 404) {
            // 结果未到达，继续轮询
            console.log('结果未到达，继续等待...');
        } else {
            // 其他错误
            stopPolling();
            hideLoading();
            alert('查询结果时出错');
            document.getElementById('submitBtn').disabled = false;
            console.error('查询错误，状态码:', response.status);
        }
    } catch (error) {
        // 网络错误，不停止轮询（可能是暂时中断）
        console.error('轮询请求失败:', error);
    }
}

/**
 * 停止轮询定时器
 * 功能：清除定时器并将 pollingTimer 置为 null
 */
function stopPolling() {
    if (appState.pollingTimer) {
        clearInterval(appState.pollingTimer);
        appState.pollingTimer = null;
        console.log('停止轮询');
    }
}

// ============================================
// 步骤6：重构 displayResult() - 结果类型判断和错误处理
// ============================================

/**
 * 在页面上展示分析结果或错误信息
 * 功能：
 * 1. 隐藏加载指示器
 * 2. 重置 UI（清空之前的画布和报告）
 * 3. 根据结果状态进行路由
 * 4. 成功时根据任务类型调用对应的渲染函数
 * 5. 失败时显示错误信息
 */
function displayResult(resultJson) {
    console.log('displayResult 被调用，结果:', resultJson);
    
    // 隐藏加载指示器
    hideLoading();
    
    // 检查是否为 mock 数据
    if (resultJson.is_mock === true) {
        alert('后端无模型权重，本次结果为示例json');
        console.log('检测到 mock 数据，已弹窗提示用户');
    }
    
    // 重置 UI（清空之前的画布和报告）
    clearCanvas();
    clearReport();
    
    // 判断结果状态
    if (resultJson.status === 'FAILURE') {
        console.log('结果状态为 FAILURE');
        displayError(resultJson.error);
        return;
    }
    
    // SUCCESS 状态：根据任务类型渲染
    const taskType = appState.currentTaskType;
    const data = resultJson.data;
    
    console.log('任务类型:', taskType, '数据:', data);
    
    if (!taskType) {
        console.error('任务类型未设置');
        displayError({ displayMessage: '任务类型未设置，无法显示结果' });
        return;
    }
    
    if (!data) {
        console.error('数据为空');
        displayError({ displayMessage: '分析结果数据为空' });
        return;
    }
    
    if (taskType === 'cephalometric') {
        console.log('调用 renderCephalometric');
        renderCephalometric(data);
    } else if (taskType === 'panoramic') {
        console.log('调用 renderPanoramic');
        renderPanoramic(data);
    } else if (taskType === 'dental_age_stage') {
        console.log('调用 renderDentalAgeStage');
        renderDentalAgeStage(data);
    } else {
        console.error('未知的任务类型:', taskType);
        displayError({ displayMessage: '未知的任务类型: ' + taskType });
    }
    
    // 重新启用提交按钮（允许提交新任务）
    document.getElementById('submitBtn').disabled = false;
}

/**
 * 手动可视化：上传图片 + JSON，本地渲染（支持全景/侧位）
 */
async function onManualVisualize() {
    const taskSelect = document.getElementById('manualTaskType');
    const imageInput = document.getElementById('manualImageFile');
    const jsonInput = document.getElementById('manualJsonFile');
    const jsonTextArea = document.getElementById('manualJsonText');

    if (!taskSelect || !imageInput || !jsonInput || !jsonTextArea) {
        console.warn('手动可视化控件不存在，跳过');
        return;
    }

    const taskType = taskSelect.value || 'cephalometric';
    const imageFile = imageInput.files[0];

    if (!imageFile) {
        alert('请先上传图片文件');
        return;
    }

    let data;
    try {
        data = await loadManualJson(jsonInput.files[0], jsonTextArea.value);
    } catch (err) {
        console.error('手动可视化 JSON 解析失败', err);
        alert('JSON 解析失败，请检查格式');
        return;
    }

    if (!data) {
        alert('请上传或粘贴 JSON 数据');
        return;
    }

    let img;
    try {
        img = await loadImageFile(imageFile);
    } catch (err) {
        console.error('手动可视化图片加载失败', err);
        alert('图片加载失败，请检查文件格式');
        return;
    }

    // 重置画布与报告
    clearCanvas();
    clearReport();

    // 缓存状态并按任务类型渲染
    appState.originalImage = img;
    appState.cachedResult = { taskType, data };
    appState.currentTaskType = taskType;
    appState.imageScale = 1.0;

    if (taskType === 'cephalometric') {
        renderCephalometric(data);
    } else if (taskType === 'panoramic') {
        renderPanoramic(data);
    } else {
        alert('未知任务类型，请选择全景或侧位');
    }
}

/**
 * 显示错误信息
 * @param {Object} error - 错误对象
 */
function displayError(error) {
    const errorMessage = document.getElementById('errorMessage');
    const mainContainer = document.getElementById('mainContainer');
    
    // 隐藏主容器
    if (mainContainer) {
        mainContainer.classList.add('hidden');
    }
    
    // 显示错误提示
    const errorText = error?.displayMessage || '未知错误';
    if (errorMessage) {
        errorMessage.textContent = errorText;
        errorMessage.classList.remove('hidden');
    }
    
    console.log('错误展示:', errorText);
    
    // 重新启用提交按钮
    document.getElementById('submitBtn').disabled = false;
}

/**
 * 清空 Canvas 和 Konva 对象
 */
function clearCanvas() {
    if (appState.konvaStage) {
        // 销毁所有图层
        appState.konvaStage.destroyChildren();
        // 销毁 Stage
        appState.konvaStage.destroy();
        appState.konvaStage = null;
    }
    appState.konvaLayers = {};
    appState.originalImage = null;
    appState.imageScale = 1.0;
    appState.layerVisibility = {};
    
    // 隐藏图层控制面板
    const panel = document.getElementById('layerControlPanel');
    if (panel) {
        panel.style.display = 'none';
    }

    const tools = document.getElementById('measurementTools');
    if (tools) {
        tools.classList.add('hidden');
    }
}

/**
 * 清空报告容器
 */
function clearReport() {
    const reportContent = document.getElementById('reportContent');
    if (reportContent) {
        reportContent.innerHTML = '';
    }
}

/**
 * 读取手动可视化 JSON（优先文件，其次文本）
 */
async function loadManualJson(file, text) {
    if (file) {
        const content = await file.text();
        return JSON.parse(content);
    }
    const trimmed = (text || '').trim();
    if (trimmed) {
        return JSON.parse(trimmed);
    }
    return null;
}

/**
 * 从文件加载图片，返回 Image 对象
 */
function loadImageFile(file) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = (err) => reject(err || new Error('图片加载失败'));
        img.src = URL.createObjectURL(file);
    });
}

/**
 * 计算文件的 SHA-256（用于示例识别，可选）
 */
async function computeSHA256(file) {
    const buffer = await file.arrayBuffer();
    const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * 检测是否为已知的示例全景图（带水印的上传文件）
 * 优先通过文件名关键词；若配置了哈希则使用哈希匹配
 */
async function detectDemoPanoramicCase(file) {
    const DEMO_JSON_MAP = {
        liang: { json: '/static/examples/liang.json', keywords: ['liang'] },
        lin: { json: '/static/examples/lin.json', keywords: ['lin'] },
    };

    // 1) 文件名关键词匹配
    const name = (file.name || '').toLowerCase();
    for (const [key, info] of Object.entries(DEMO_JSON_MAP)) {
        if (info.keywords && info.keywords.some(k => name.includes(k))) {
            return { key, json: info.json };
        }
    }

    // 2) 如需哈希匹配，可在此配置预先计算好的哈希（可选，留空不影响）
    const DEMO_HASHES = {
        // 'sha256-of-liang_wm.jpg': 'liang',
        // 'sha256-of-lin_wm.jpg': 'lin',
    };
    if (Object.keys(DEMO_HASHES).length > 0) {
        const sha = await computeSHA256(file);
        const hitKey = DEMO_HASHES[sha];
        if (hitKey && DEMO_JSON_MAP[hitKey]) {
            return { key: hitKey, json: DEMO_JSON_MAP[hitKey].json };
        }
    }

    return null;
}

/**
 * 创建“复制 JSON”按钮
 */
function createCopyJsonButton(jsonContent) {
    const copyBtn = document.createElement('button');
    copyBtn.className = 'json-toggle-btn';
    copyBtn.textContent = '复制 JSON';
    copyBtn.style.marginLeft = '8px';
    copyBtn.onclick = async function() {
        try {
            await navigator.clipboard.writeText(jsonContent.textContent);
            alert('JSON 已复制到剪贴板');
        } catch (e) {
            console.error('复制 JSON 失败', e);
            alert('复制失败，请手动复制');
        }
    };
    return copyBtn;
}

/**
 * 标签页切换：aiTab / manualTab
 */
function switchTab(tabName) {
    const panels = document.querySelectorAll('.tab-panel');
    const buttons = document.querySelectorAll('.tab-btn');
    panels.forEach(p => {
        if (p.id === tabName) {
            p.classList.remove('hidden');
        } else {
            p.classList.add('hidden');
        }
    });
    buttons.forEach(b => {
        if (b.getAttribute('data-tab') === tabName) {
            b.classList.add('active');
        } else {
            b.classList.remove('active');
        }
    });
}

/**
 * 渲染牙期检测结果
 * @param {Object} data - 牙期检测数据
 */
function renderDentalAgeStage(data) {
    console.log('开始渲染牙期检测结果...', data);
    
    // 显示主容器
    const mainContainer = document.getElementById('mainContainer');
    if (mainContainer) {
        mainContainer.classList.remove('hidden');
    }
    
    // 生成文本报告
    const reportContent = document.getElementById('reportContent');
    if (reportContent) {
        const stage = data.dentalAgeStage || '未知';
        const analysis = data.teethAnalysis || {};
        const total = analysis.totalDetected || 0;
        const deciduous = analysis.deciduousCount || 0;
        const permanent = analysis.permanentCount || 0;
        
        let stageText = stage;
        if (stage === 'Mixed') stageText = '混合牙期 (Mixed)';
        else if (stage === 'Permanent') stageText = '恒牙期 (Permanent)';
        
        let html = `
            <div class="report-section">
                <h2 class="report-title">牙期检测报告</h2>
                
                <div class="measurement-group">
                    <h3>检测结论</h3>
                    <div class="measurement-item">
                        <span class="label">牙期阶段:</span>
                        <span class="value" style="font-weight: bold; color: #2c3e50;">${stageText}</span>
                    </div>
                </div>
                
                <div class="measurement-group">
                    <h3>牙齿统计</h3>
                    <div class="measurement-item">
                        <span class="label">检测总数:</span>
                        <span class="value">${total}</span>
                    </div>
                    <div class="measurement-item">
                        <span class="label">乳牙数量:</span>
                        <span class="value">${deciduous}</span>
                    </div>
                    <div class="measurement-item">
                        <span class="label">恒牙数量:</span>
                        <span class="value">${permanent}</span>
                    </div>
                </div>
                
                <div class="measurement-group">
                    <h3>详细列表</h3>
                    <div class="measurement-item" style="flex-direction: column; align-items: flex-start;">
                        <span class="label" style="margin-bottom: 5px;">乳牙 (FDI):</span>
                        <span class="value" style="word-break: break-all; line-height: 1.4;">${(analysis.deciduousTeeth || []).join(', ') || '无'}</span>
                    </div>
                    <div class="measurement-item" style="flex-direction: column; align-items: flex-start; margin-top: 10px;">
                        <span class="label" style="margin-bottom: 5px;">恒牙 (FDI):</span>
                        <span class="value" style="word-break: break-all; line-height: 1.4;">${(analysis.permanentTeeth || []).join(', ') || '无'}</span>
                    </div>
                </div>
            </div>
        `;
        
        reportContent.innerHTML = html;
        
        // 添加完整 JSON 数据输出（可展开/折叠），与全景和侧位保持一致
        const jsonSection = createReportSection('完整数据 (JSON)');
        const jsonToggle = document.createElement('button');
        jsonToggle.className = 'json-toggle-btn';
        jsonToggle.textContent = '展开 JSON 数据';
        jsonToggle.onclick = function() {
            const jsonContent = jsonSection.querySelector('.json-content');
            if (jsonContent) {
                if (jsonContent.style.display === 'none') {
                    jsonContent.style.display = 'block';
                    jsonToggle.textContent = '折叠 JSON 数据';
                } else {
                    jsonContent.style.display = 'none';
                    jsonToggle.textContent = '展开 JSON 数据';
                }
            }
        };
        jsonSection.appendChild(jsonToggle);
        
        const jsonContent = document.createElement('pre');
        jsonContent.className = 'json-content';
        jsonContent.style.display = 'none';
        jsonContent.style.whiteSpace = 'pre-wrap';
        jsonContent.style.wordWrap = 'break-word';
        jsonContent.style.fontSize = '11px';
        jsonContent.style.backgroundColor = '#f5f5f5';
        jsonContent.style.padding = '10px';
        jsonContent.style.borderRadius = '4px';
        jsonContent.style.overflowX = 'auto';
        jsonContent.textContent = JSON.stringify(data, null, 2);
        jsonSection.appendChild(jsonContent);

        jsonSection.appendChild(createCopyJsonButton(jsonContent));
        
        reportContent.appendChild(jsonSection);
    }
    
    // 加载并显示原图
    const imageFile = document.getElementById('imageFile').files[0];
    if (!imageFile) {
        console.error('未找到图片文件');
        return;
    }
    
    const img = new Image();
    img.onerror = function() {
        console.error('图片加载失败');
        displayError({ displayMessage: '图片加载失败' });
    };
    
    img.onload = function() {
        const container = document.getElementById('imageContainer');
        if (!container) return;
        
        const containerWidth = container.clientWidth;
        const containerHeight = container.clientHeight;
        
        // 计算缩放比例
        let scale = 1.0;
        if (containerWidth > 0 && containerHeight > 0) {
            const scaleX = containerWidth / img.width;
            const scaleY = containerHeight / img.height;
            scale = Math.min(scaleX, scaleY, 1.0);
        }
        
        const displayWidth = img.width * scale;
        const displayHeight = img.height * scale;
        
        // 初始化 Stage
        const stage = initKonvaStage('imageContainer', displayWidth, displayHeight);
        if (!stage) return;
        
        // 创建背景层
        const bgLayer = new Konva.Layer();
        const bgImage = new Konva.Image({
            x: 0,
            y: 0,
            image: img,
            width: displayWidth,
            height: displayHeight
        });
        bgLayer.add(bgImage);
        stage.add(bgLayer);
        
        // 保存状态
        appState.konvaStage = stage;
        appState.originalImage = img;
        appState.imageScale = scale;
        appState.konvaLayers['background'] = bgLayer;
        
        stage.draw();
        
        // 如果有 initLayerControlPanel 函数，调用它
        if (typeof initLayerControlPanel === 'function') {
            initLayerControlPanel();
        }
    };
    
    img.src = URL.createObjectURL(imageFile);
}

// ============================================
// 步骤7：侧位片渲染 - 背景图加载和关键点绘制
// ============================================

// 关键点全名映射表（完整英文名称 -> 中文名称）
// 新规范中 Landmarks 的 Label 已经是完整英文名称
const LANDMARK_FULL_NAMES = {
    // 完整英文名称 -> 中文
    'Sella': '蝶鞍点',
    'Nasion': '鼻根点',
    'Orbitale': '眶下点',
    'Porion': '耳点',
    'Subspinale': '上齿槽座点',
    'Supramentale': '下齿槽座点',
    'Pogonion': '颏前点',
    'Menton': '颏下点',
    'Gnathion': '颏顶点',
    'Gonion': '下颌角点',
    'Incision inferius': '下中切牙切点',
    'Incision superius': '上中切牙切点',
    'Posterior nasal spine': '后鼻棘点',
    'Anterior nasal spine': '前鼻棘点',
    'Articulare': '关节点',
    'Co': '髁顶点',
    'PTM': '翼上颌裂',
    'Pt': '翼点',
    'U1A': '上中切牙根尖点',
    'L1A': '下中切牙根尖点',
    'U6': '上颌第一磨牙近中颊尖点',
    'L6': '下颌第一磨牙近中颊尖点',
    'Ba': '颅底点',
    'Bo': '颅底角点',
    'Pcd': '下颌髁突后缘切点',
    // 兼容旧格式简称
    'S': '蝶鞍点',
    'N': '鼻根点',
    'Or': '眶下点',
    'Po': '耳点',
    'A': '上齿槽座点',
    'B': '下齿槽座点',
    'Pog': '颏前点',
    'Me': '颏下点',
    'Gn': '颏顶点',
    'Go': '下颌角点',
    'L1': '下中切牙点',
    'UI': '上中切牙切点',
    'PNS': '后鼻棘点',
    'ANS': '前鼻棘点',
    'Ar': '关节点'
};

/**
 * 渲染侧位片结果（支持图片和 DICOM）
 * @param {Object} data - 侧位片分析数据
 */
async function renderCephalometric(data) {
    console.log('开始渲染侧位片结果...', data);
    
    // 先显示主容器和报告区域（即使图片还没加载）
    const mainContainer = document.getElementById('mainContainer');
    if (mainContainer) {
        mainContainer.classList.remove('hidden');
    }
    
    // 预先缓存点位与测量列表，供可视化渲染使用
    appState.cephLandmarks = buildLandmarkMap(data);
    appState.cephMeasurements = data?.CephalometricMeasurements?.AllMeasurements || [];
    appState.activeMeasurementLabel = null;
    const tools = document.getElementById('measurementTools');
    if (tools) {
        tools.classList.remove('hidden');
    }
    
    // 生成结构化报告
    buildCephReport(data);
    
    // ================= 修改开始：优先使用缓存的原始图片 =================
    // 1. 优先使用缓存的原始图片，否则从文件加载
    let img = appState.originalImage;
    
    if (!img) {
        const file = document.getElementById('imageFile').files[0];
        if (!file) {
            console.error('未找到文件');
            // 只有在没有缓存且没有文件时才报错
            if (!appState.originalImage) {
                displayError({ displayMessage: '未找到上传的文件' });
                return;
            }
        } else {
            console.log('找到文件:', file.name, '大小:', file.size);
            try {
                img = await new Promise((resolve, reject) => {
                    const image = new Image();
                    image.onload = () => resolve(image);
                    image.onerror = reject;
                    image.src = URL.createObjectURL(file);
                });
            } catch (error) {
                console.error('文件加载失败:', error);
                displayError({ displayMessage: '文件加载失败' });
                return;
            }
        }
    }
    // ================= 修改结束 =================
    
    console.log('图像加载成功，尺寸:', img.width, 'x', img.height);
    
    // 3. 获取容器尺寸，计算缩放比例以适应容器
    const container = document.getElementById('imageContainer');
    if (!container) {
        console.error('图像容器不存在');
        return;
    }
    
    const containerWidth = container.clientWidth;
    const containerHeight = container.clientHeight;
    
    console.log('容器尺寸:', containerWidth, 'x', containerHeight);
    
    // 计算缩放比例
    let scale = 1.0;
    let displayWidth = img.width;
    let displayHeight = img.height;
    
    if (containerWidth > 0 && containerHeight > 0) {
        const scaleX = containerWidth / img.width;
        const scaleY = containerHeight / img.height;
        scale = Math.min(scaleX, scaleY, 1.0); // 不放大，只缩小
        displayWidth = img.width * scale;
        displayHeight = img.height * scale;
    }
    
    console.log('缩放比例:', scale, '显示尺寸:', displayWidth, 'x', displayHeight);
    
    // 保存缩放比例
    appState.imageScale = scale;
    appState.originalImage = img;
    
    // 4. 初始化 Konva Stage
    const stage = initKonvaStage('imageContainer', displayWidth, displayHeight);
    if (!stage) {
        console.error('Konva Stage 初始化失败');
        return;
    }
    
    // 5. 创建背景图层并添加图片
    const bgLayer = new Konva.Layer();
    const bgImage = new Konva.Image({
        x: 0,
        y: 0,
        image: img,
        width: displayWidth,
        height: displayHeight
    });
    bgLayer.add(bgImage);
    stage.add(bgLayer);
    appState.konvaLayers.background = bgLayer;
    
    // 5.5. 创建测量线图层（在关键点层之前，确保关键点显示在测量线之上）
    const measurementLayer = new Konva.Layer();
    stage.add(measurementLayer);
    appState.konvaLayers.measurementLines = measurementLayer;
    appState.layerVisibility.measurementLines = true;
    
    // 6. 绘制关键点
    drawLandmarks(data, stage, scale);
    
    // 7. 绘制 CVM 边界框
    drawCVMBox(data, stage, scale);
    
    // 绘制画布
    stage.draw();
    
    // 8. 初始化图层控制面板
    initLayerControlPanel();

    // 9. 自动渲染首个可视化测量项
    const first = getNavigableMeasurements()[0];
    if (first) {
        handleMeasurementClick(first);
    } else {
        console.warn('未找到可视化测量项，无法自动渲染');
    }
    
    console.log('侧位片渲染完成');
}

/**
 * 绘制关键点
 * @param {Object} data - 侧位片分析数据
 * @param {Konva.Stage} stage - Konva Stage 实例
 * @param {number} scale - 缩放比例
 */
function drawLandmarks(data, stage, scale) {
    // 创建关键点图层
    const landmarkLayer = new Konva.Layer();
    
    // 遍历 Landmarks 数组，绘制关键点
    if (data.LandmarkPositions && data.LandmarkPositions.Landmarks) {
        const landmarks = data.LandmarkPositions.Landmarks;
        console.log('开始绘制关键点，总数:', landmarks.length);
        
        let drawnCount = 0;
        landmarks.forEach(landmark => {
            // 跳过缺失的点或坐标无效的点
            if (landmark.Status === 'Missing' || landmark.X === undefined || landmark.Y === undefined || landmark.X === null || landmark.Y === null) {
                return;
            }
            
            // 应用缩放比例
            const scaledX = landmark.X * scale;
            const scaledY = landmark.Y * scale;
            
            // 绘制圆点（医学精确点，使用较小半径）
            const circle = new Konva.Circle({
                x: scaledX,
                y: scaledY,
                radius: 2,
                fill: 'red',
                stroke: '#ff0000',
                strokeWidth: CONFIG.STROKE_WIDTH
            });
            
            // 绘制标签文本
            const text = new Konva.Text({
                x: scaledX + 5,
                y: scaledY - 6,
                text: landmark.Label,
                fontSize: 10,
                fill: 'white',
                padding: 1,
                backgroundColor: 'rgba(0,0,0,0.6)'
            });
            
            // 存储关键点数据到图形对象，用于后续 Tooltip
            circle.landmarkData = landmark;
            text.landmarkData = landmark;
            
            // 绑定 Tooltip 事件
            circle.on('mouseenter', function(e) {
                showLandmarkTooltip(this, landmark, e);
            });
            
            circle.on('mouseleave', function() {
                hideTooltip();
            });
            
            // 文本也绑定事件（可选，提供更大的悬停区域）
            text.on('mouseenter', function(e) {
                showLandmarkTooltip(this, landmark, e);
            });
            
            text.on('mouseleave', function() {
                hideTooltip();
            });
            
            // 添加点击切换图层显示/隐藏功能
            addClickToggleToNode(circle, 'landmarks');
            addClickToggleToNode(text, 'landmarks');
            
            landmarkLayer.add(circle);
            landmarkLayer.add(text);
            drawnCount++;
        });
        
        console.log('关键点绘制完成，已绘制:', drawnCount, '个');
    } else {
        console.warn('未找到关键点数据，data.LandmarkPositions:', data.LandmarkPositions);
    }
    
    stage.add(landmarkLayer);
    appState.konvaLayers.landmarks = landmarkLayer;
}

/**
 * 绘制 CVM 边界框（颈椎成熟度检测区域）
 * @param {Object} data - 侧位片分析数据
 * @param {Konva.Stage} stage - Konva Stage 实例
 * @param {number} scale - 缩放比例
 */
function drawCVMBox(data, stage, scale) {
    // 查找 CVM 测量项
    if (!data.CephalometricMeasurements || !data.CephalometricMeasurements.AllMeasurements) {
        console.log('未找到测量数据，跳过 CVM 边界框绘制');
        return;
    }
    
    const measurements = data.CephalometricMeasurements.AllMeasurements;
    const cvmMeasurement = measurements.find(m => m.Label === 'Cervical_Vertebral_Maturity_Stage');
    
    if (!cvmMeasurement || !cvmMeasurement.Coordinates || cvmMeasurement.Coordinates.length === 0) {
        console.log('未找到 CVM 测量数据或 Coordinates 为空，跳过 CVM 边界框绘制');
        return;
    }
    
    const coordinates = cvmMeasurement.Coordinates;
    const level = cvmMeasurement.Level || 0;
    const confidence = cvmMeasurement.Confidence || 0.0;
    
    console.log('绘制 CVM 边界框，Level:', level, 'Confidence:', confidence, 'Coordinates:', coordinates);
    
    // 创建 CVM 图层
    const cvmLayer = new Konva.Layer();
    
    // 将坐标数组转换为 Konva.Line 需要的格式（一维数组）
    // Coordinates 格式：[[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
    const points = [];
    coordinates.forEach(coord => {
        if (coord && coord.length >= 2) {
            const x = coord[0] * scale;
            const y = coord[1] * scale;
            points.push(x, y);
        }
    });
    
    if (points.length < 6) { // 至少需要 3 个点（6 个值）
        console.warn('CVM Coordinates 点数不足，跳过绘制');
        return;
    }
    
    // 绘制边界框（使用闭合的多边形）
    // 使用柔和的绿色（降低饱和度）
    const cvmBox = new Konva.Line({
        points: points,
        closed: true,
        stroke: '#7cb342', // 柔和的绿色边框（降低饱和度）
        strokeWidth: 2,
        lineCap: 'round',
        lineJoin: 'round',
        fill: 'rgba(124, 179, 66, 0.1)', // 半透明柔和绿色填充
        strokeScaleEnabled: false // 禁止线条随缩放变粗
    });
    
    // 添加标签文本（只显示 CS 阶段）
    const labelText = `CS${level}`;
    const text = new Konva.Text({
        x: points[0] + 5, // 在第一个点附近显示
        y: points[1] - 15,
        text: labelText,
        fontSize: 12,
        fontFamily: 'Arial',
        fill: '#7cb342', // 柔和的绿色
        padding: 2,
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        align: 'left'
    });
    
    // 添加鼠标悬停提示
    cvmBox.on('mouseenter', function(e) {
        showCVMTooltip(this, { level, confidence, coordinates }, e);
    });
    cvmBox.on('mouseleave', function() {
        hideTooltip();
    });
    text.on('mouseenter', function(e) {
        showCVMTooltip(cvmBox, { level, confidence, coordinates }, e);
    });
    text.on('mouseleave', function() {
        hideTooltip();
    });
    
    // 添加点击切换图层显示/隐藏功能
    addClickToggleToNode(cvmBox, 'cvm');
    addClickToggleToNode(text, 'cvm');
    
    cvmLayer.add(cvmBox);
    cvmLayer.add(text);
    stage.add(cvmLayer);
    appState.konvaLayers.cvm = cvmLayer;
    
    console.log('CVM 边界框绘制完成');
}

// ============================================
// 步骤8：侧位片 Tooltip 交互
// ============================================

/**
 * 显示 CVM Tooltip
 * @param {Konva.Node} node - Konva 节点（Line 或 Text）
 * @param {Object} cvmData - CVM 数据 {level, confidence, coordinates}
 * @param {Object} event - Konva 事件对象
 */
function showCVMTooltip(node, cvmData, event) {
    // 移除已存在的 Tooltip
    hideTooltip();
    
    const { level } = cvmData;
    
    // 创建 Tooltip 元素
    const tooltip = document.createElement('div');
    tooltip.id = 'cvmTooltip';
    tooltip.className = 'tooltip';
    
    // 构建 Tooltip 内容（只显示中文阶段）
    let content = `CS${level}阶段`;
    
    tooltip.innerHTML = content;
    
    // 获取 Stage 的位置
    const stage = node.getStage();
    const stageBox = stage.container().getBoundingClientRect();
    
    // 获取节点在 Stage 中的位置
    const nodePos = node.getAbsolutePosition();
    
    // 计算 Tooltip 位置（相对于页面）
    const tooltipX = stageBox.left + nodePos.x + 15;
    const tooltipY = stageBox.top + nodePos.y - 10;
    
    // 设置 Tooltip 位置
    tooltip.style.left = tooltipX + 'px';
    tooltip.style.top = tooltipY + 'px';
    
    // 添加到页面
    document.body.appendChild(tooltip);
    
    // 调整位置，确保不超出视口
    const tooltipRect = tooltip.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    
    if (tooltipRect.right > viewportWidth) {
        tooltip.style.left = (tooltipX - tooltipRect.width - 30) + 'px';
    }
    
    if (tooltipRect.bottom > viewportHeight) {
        tooltip.style.top = (tooltipY - tooltipRect.height) + 'px';
    }
    
    if (tooltipRect.left < 0) {
        tooltip.style.left = '10px';
    }
    
    if (tooltipRect.top < 0) {
        tooltip.style.top = '10px';
    }
}

/**
 * 显示关键点 Tooltip
 * @param {Konva.Node} node - Konva 节点（Circle 或 Text）
 * @param {Object} landmark - 关键点数据
 * @param {Object} event - Konva 事件对象
 */
function showLandmarkTooltip(node, landmark, event) {
    // 移除已存在的 Tooltip
    hideTooltip();
    
    // 获取关键点全名（新规范中 Label 已经是完整英文名称）
    const fullName = LANDMARK_FULL_NAMES[landmark.Label] || landmark.Label;
    
    // 创建 Tooltip 元素
    const tooltip = document.createElement('div');
    tooltip.id = 'landmarkTooltip';
    tooltip.className = 'tooltip';
    
    // 构建 Tooltip 内容
    let content = `<strong>${fullName}</strong><br>`;
    content += `标签: ${landmark.Label}<br>`;
    // 新规范中坐标是整数，但也兼容小数格式
    const xDisplay = Number.isInteger(landmark.X) ? landmark.X : landmark.X.toFixed(1);
    const yDisplay = Number.isInteger(landmark.Y) ? landmark.Y : landmark.Y.toFixed(1);
    content += `坐标: (${xDisplay}, ${yDisplay})`;
    // 置信度已隐藏 - 不再显示
    
    tooltip.innerHTML = content;
    
    // 获取 Stage 的位置
    const stage = node.getStage();
    const stageBox = stage.container().getBoundingClientRect();
    
    // 获取节点在 Stage 中的位置
    const nodePos = node.getAbsolutePosition();
    
    // 计算 Tooltip 位置（相对于页面）
    const tooltipX = stageBox.left + nodePos.x + 15;
    const tooltipY = stageBox.top + nodePos.y - 10;
    
    // 设置 Tooltip 位置
    tooltip.style.left = tooltipX + 'px';
    tooltip.style.top = tooltipY + 'px';
    
    // 添加到页面
    document.body.appendChild(tooltip);
    
    // 调整位置，确保不超出视口
    const tooltipRect = tooltip.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    
    if (tooltipRect.right > viewportWidth) {
        tooltip.style.left = (tooltipX - tooltipRect.width - 30) + 'px';
    }
    
    if (tooltipRect.bottom > viewportHeight) {
        tooltip.style.top = (tooltipY - tooltipRect.height) + 'px';
    }
    
    if (tooltipRect.left < 0) {
        tooltip.style.left = '10px';
    }
    
    if (tooltipRect.top < 0) {
        tooltip.style.top = '10px';
    }
}

/**
 * 隐藏 Tooltip
 */
function hideTooltip() {
    const tooltip = document.getElementById('landmarkTooltip');
    if (tooltip) {
        tooltip.remove();
    }
    const toothTooltip = document.getElementById('toothTooltip');
    if (toothTooltip) {
        toothTooltip.remove();
    }
    const findingTooltip = document.getElementById('findingTooltip');
    if (findingTooltip) {
        findingTooltip.remove();
    }
    const cvmTooltip = document.getElementById('cvmTooltip');
    if (cvmTooltip) {
        cvmTooltip.remove();
    }
}

/**
 * 显示牙齿 Tooltip
 * @param {Konva.Node} node - Konva 节点（Line）
 * @param {Object} toothData - 牙齿数据
 * @param {Object} event - Konva 事件对象
 */
function showToothTooltip(node, toothData, event) {
    // 移除已存在的 Tooltip
    hideTooltip();
    
    // 创建 Tooltip 元素
    const tooltip = document.createElement('div');
    tooltip.id = 'toothTooltip';
    tooltip.className = 'tooltip';
    
    // 构建 Tooltip 内容
    let content = `<strong>牙位: ${toothData.FDI || 'N/A'}</strong><br>`;
    
    // 汇总该牙齿的所有属性类发现
    if (toothData.Properties && Array.isArray(toothData.Properties) && toothData.Properties.length > 0) {
        content += '<br>发现:<br>';
        toothData.Properties.forEach(prop => {
            const description = prop.Description || prop.Value || '未知';
            const confidence = prop.Confidence !== undefined ? (prop.Confidence * 100).toFixed(1) : 'N/A';
            content += `- ${description} (置信度: ${confidence}%)<br>`;
        });
    } else {
        content += '<br>未发现异常';
    }
    
    tooltip.innerHTML = content;
    
    // 获取 Stage 的位置
    const stage = node.getStage();
    const stageBox = stage.container().getBoundingClientRect();
    
    // 获取节点在 Stage 中的位置（使用多边形的中心点）
    const points = node.points();
    let sumX = 0, sumY = 0, pointCount = 0;
    for (let i = 0; i < points.length; i += 2) {
        sumX += points[i];
        sumY += points[i + 1];
        pointCount++;
    }
    const centerX = sumX / pointCount;
    const centerY = sumY / pointCount;
    
    // 计算 Tooltip 位置（相对于页面）
    const tooltipX = stageBox.left + centerX + 15;
    const tooltipY = stageBox.top + centerY - 10;
    
    // 设置 Tooltip 位置
    tooltip.style.left = tooltipX + 'px';
    tooltip.style.top = tooltipY + 'px';
    
    // 添加到页面
    document.body.appendChild(tooltip);
    
    // 调整位置，确保不超出视口
    const tooltipRect = tooltip.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    
    if (tooltipRect.right > viewportWidth) {
        tooltip.style.left = (tooltipX - tooltipRect.width - 30) + 'px';
    }
    
    if (tooltipRect.bottom > viewportHeight) {
        tooltip.style.top = (tooltipY - tooltipRect.height) + 'px';
    }
    
    if (tooltipRect.left < 0) {
        tooltip.style.left = '10px';
    }
    
    if (tooltipRect.top < 0) {
        tooltip.style.top = '10px';
    }
}

/**
 * 显示区域性发现 Tooltip
 * @param {Konva.Node} node - Konva 节点（Rect）
 * @param {Object} findingData - 发现数据
 * @param {Object} event - Konva 事件对象
 */
function showFindingTooltip(node, findingData, event) {
    // 移除已存在的 Tooltip
    hideTooltip();
    
    // 创建 Tooltip 元素
    const tooltip = document.createElement('div');
    tooltip.id = 'findingTooltip';
    tooltip.className = 'tooltip';
    
    // 构建 Tooltip 内容
    let content = '';
    
    // 根据发现类型显示不同的标题
    if (node.findingType === 'implant') {
        content += '<strong>种植体</strong><br>';
    } else if (node.findingType === 'density') {
        content += '<strong>根尖密度影</strong><br>';
    } else {
        content += '<strong>区域性发现</strong><br>';
    }
    
    // 显示详细信息
    if (findingData.Detail) {
        content += `${findingData.Detail}<br>`;
    }
    
    // 显示置信度
    if (findingData.Confidence !== undefined) {
        content += `置信度: ${(findingData.Confidence * 100).toFixed(1)}%`;
    }
    
    tooltip.innerHTML = content;
    
    // 获取 Stage 的位置
    const stage = node.getStage();
    const stageBox = stage.container().getBoundingClientRect();
    
    // 获取节点在 Stage 中的位置（矩形的中心点）
    const nodePos = node.getAbsolutePosition();
    const centerX = nodePos.x + node.width() / 2;
    const centerY = nodePos.y + node.height() / 2;
    
    // 计算 Tooltip 位置（相对于页面）
    const tooltipX = stageBox.left + centerX + 15;
    const tooltipY = stageBox.top + centerY - 10;
    
    // 设置 Tooltip 位置
    tooltip.style.left = tooltipX + 'px';
    tooltip.style.top = tooltipY + 'px';
    
    // 添加到页面
    document.body.appendChild(tooltip);
    
    // 调整位置，确保不超出视口
    const tooltipRect = tooltip.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    
    if (tooltipRect.right > viewportWidth) {
        tooltip.style.left = (tooltipX - tooltipRect.width - 30) + 'px';
    }
    
    if (tooltipRect.bottom > viewportHeight) {
        tooltip.style.top = (tooltipY - tooltipRect.height) + 'px';
    }
    
    if (tooltipRect.left < 0) {
        tooltip.style.left = '10px';
    }
    
    if (tooltipRect.top < 0) {
        tooltip.style.top = '10px';
    }
}

// ============================================
// 步骤9：侧位片结构化报告生成
// ============================================

/**
 * 构建侧位片结构化报告
 * @param {Object} data - 侧位片分析数据
 */
function buildCephReport(data) {
    const container = document.getElementById('reportContent');
    if (!container) {
        console.error('报告内容容器不存在');
        return;
    }
    
    container.innerHTML = ''; // 清空
    
    // 1. 分析摘要
    const summarySection = createReportSection('分析摘要');
    if (data.VisibilityMetrics) {
        summarySection.appendChild(createKeyValue('可见性等级', data.VisibilityMetrics.Grade || 'N/A'));
    }
    if (data.StatisticalFields) {
        // 质量评分：确保在0-100%范围内
        const qualityScore = data.StatisticalFields.QualityScore;
        const qualityPercent = qualityScore > 1 ? qualityScore : (qualityScore * 100);
        summarySection.appendChild(createKeyValue('质量评分', qualityPercent.toFixed(1) + '%'));
        // 平均置信度已隐藏 - 不再显示
        
        // 已检测关键点：显示具体点列表
        const detectedCount = data.StatisticalFields.ProcessedLandmarks || 0;
        const totalCount = data.LandmarkPositions?.TotalLandmarks || 0;
        const detectedPointsDiv = document.createElement('div');
        detectedPointsDiv.className = 'key-value-item';
        detectedPointsDiv.innerHTML = `<span class="key">已检测关键点:</span> <span class="value">${detectedCount}/${totalCount}</span>`;
        summarySection.appendChild(detectedPointsDiv);
        
        // 显示具体检测到的关键点列表
        if (data.LandmarkPositions && data.LandmarkPositions.Landmarks) {
            const detectedLabels = data.LandmarkPositions.Landmarks
                .filter(l => l.Status === 'Detected' && l.X !== undefined && l.X !== null && l.Y !== undefined && l.Y !== null)
                .map(l => {
                    // 新规范中 Label 已经是完整英文名称，映射到中文
                    const chineseName = LANDMARK_FULL_NAMES[l.Label] || '';
                    return chineseName ? `${l.Label}(${chineseName})` : l.Label;
                });
            
            if (detectedLabels.length > 0) {
                const pointsListDiv = document.createElement('div');
                pointsListDiv.className = 'detected-points-list';
                pointsListDiv.innerHTML = `<div class="points-label">检测到的关键点:</div><div class="points-items">${detectedLabels.join(', ')}</div>`;
                summarySection.appendChild(pointsListDiv);
            }
            
            // 显示缺失的关键点（新规范中 MissingLandmarks 也是完整英文名称数组）
            if (data.VisibilityMetrics && data.VisibilityMetrics.MissingLandmarks && data.VisibilityMetrics.MissingLandmarks.length > 0) {
                const missingLabels = data.VisibilityMetrics.MissingLandmarks.map(label => {
                    const chineseName = LANDMARK_FULL_NAMES[label] || '';
                    return chineseName ? `${label}(${chineseName})` : label;
                });
                const missingPointsDiv = document.createElement('div');
                missingPointsDiv.className = 'missing-points-list';
                missingPointsDiv.innerHTML = `<div class="points-label">缺失的关键点:</div><div class="points-items">${missingLabels.join(', ')}</div>`;
                summarySection.appendChild(missingPointsDiv);
            }
        }
    }
    container.appendChild(summarySection);
    
    // 2. 骨骼分析
    if (data.CephalometricMeasurements && data.CephalometricMeasurements.AllMeasurements) {
        const boneSection = createReportSection('骨骼分析');
        const measurements = data.CephalometricMeasurements.AllMeasurements;
        
        measurements.forEach(m => {
            if (isBoneMeasurement(m.Label)) {
                const item = createMeasurementItem(m);
                boneSection.appendChild(item);
            }
        });
        
        if (boneSection.querySelectorAll('.measurement-item').length > 0) {
            container.appendChild(boneSection);
        }
    }
    
    // 3. 牙齿分析
    if (data.CephalometricMeasurements && data.CephalometricMeasurements.AllMeasurements) {
        const toothSection = createReportSection('牙齿分析');
        const measurements = data.CephalometricMeasurements.AllMeasurements;
        
        measurements.forEach(m => {
            if (isToothMeasurement(m.Label)) {
                const item = createMeasurementItem(m);
                toothSection.appendChild(item);
            }
        });
        
        if (toothSection.querySelectorAll('.measurement-item').length > 0) {
            container.appendChild(toothSection);
        }
    }
    
    // 4. 生长发育评估（包含所有生长相关测量项和 CVSM 图片）
    if (data.CephalometricMeasurements && data.CephalometricMeasurements.AllMeasurements) {
        const growthSection = createReportSection('生长发育评估');
        const measurements = data.CephalometricMeasurements.AllMeasurements;
        
        // 先添加所有生长发育相关的测量项
        measurements.forEach(m => {
            if (isGrowthMeasurement(m.Label)) {
                const item = createMeasurementItem(m);
                growthSection.appendChild(item);
            }
        });
        
        // 最后添加 CVSM 图片（如果有）
        const cvsm = measurements.find(m => m.Label === 'Cervical_Vertebral_Maturity_Stage');
        if (cvsm && cvsm.CVSM) {
            const img = document.createElement('img');
            img.src = cvsm.CVSM;
            img.style.maxWidth = '100%';
            img.style.marginTop = '10px';
            img.style.borderRadius = '4px';
            img.alt = '颈椎成熟度分期图像';
            growthSection.appendChild(img);
        }
        
        if (growthSection.querySelectorAll('.measurement-item, img').length > 0) {
            container.appendChild(growthSection);
        }
    }
    
    // 5. 气道分析
    if (data.CephalometricMeasurements && data.CephalometricMeasurements.AllMeasurements) {
        const airwaySection = createReportSection('气道分析');
        const measurements = data.CephalometricMeasurements.AllMeasurements;
        
        const airwayGap = measurements.find(m => m.Label === 'Airway_Gap');
        const adenoidIndex = measurements.find(m => m.Label === 'Adenoid_Index');
        
        if (airwayGap) {
            const item = createMeasurementItem(airwayGap);
            airwaySection.appendChild(item);
        }
        
        if (adenoidIndex) {
            const item = createMeasurementItem(adenoidIndex);
            airwaySection.appendChild(item);
        }
        
        if (airwaySection.querySelectorAll('.measurement-item').length > 0) {
            container.appendChild(airwaySection);
        }
    }
    
    // 6. JSON 数据输出（可展开/折叠）
    const jsonSection = createReportSection('完整数据 (JSON)');
    const jsonToggle = document.createElement('button');
    jsonToggle.className = 'json-toggle-btn';
    jsonToggle.textContent = '展开 JSON 数据';
    jsonToggle.onclick = function() {
        const jsonContent = jsonSection.querySelector('.json-content');
        if (jsonContent) {
            if (jsonContent.style.display === 'none') {
                jsonContent.style.display = 'block';
                jsonToggle.textContent = '折叠 JSON 数据';
            } else {
                jsonContent.style.display = 'none';
                jsonToggle.textContent = '展开 JSON 数据';
            }
        }
    };
    jsonSection.appendChild(jsonToggle);
    
    const jsonContent = document.createElement('pre');
    jsonContent.className = 'json-content';
    jsonContent.style.display = 'none';
    jsonContent.style.whiteSpace = 'pre-wrap';
    jsonContent.style.wordWrap = 'break-word';
    jsonContent.style.fontSize = '11px';
    jsonContent.style.backgroundColor = '#f5f5f5';
    jsonContent.style.padding = '10px';
    jsonContent.style.borderRadius = '4px';
    jsonContent.style.overflowX = 'auto';
    jsonContent.textContent = JSON.stringify(data, null, 2);
    jsonSection.appendChild(jsonContent);
    jsonSection.appendChild(createCopyJsonButton(jsonContent));
    
    container.appendChild(jsonSection);
}

/**
 * 创建报告区块
 * @param {string} title - 区块标题
 * @returns {HTMLElement} 报告区块元素
 */
function createReportSection(title) {
    const section = document.createElement('div');
    section.className = 'report-section';
    
    const h2 = document.createElement('h2');
    h2.textContent = title;
    section.appendChild(h2);
    
    return section;
}

/**
 * 创建键值对元素
 * @param {string} key - 键名
 * @param {string|number} value - 值
 * @returns {HTMLElement} 键值对元素
 */
function createKeyValue(key, value) {
    const div = document.createElement('div');
    div.className = 'key-value-item';
    div.innerHTML = `<span class="key">${key}:</span> <span class="value">${value}</span>`;
    return div;
}

/**
 * 创建测量项元素
 * @param {Object} measurement - 测量项数据
 * @returns {HTMLElement} 测量项元素
 */
function createMeasurementItem(measurement) {
    const item = document.createElement('div');
    item.className = 'measurement-item';
    item.dataset.label = measurement.Label || '';
    
    // 判断是否为未检测状态：Level === -1 或 Level === null 或 Level === [-1]
    const isUndetected = measurement.Level === -1 || 
                         measurement.Level === null ||
                         (Array.isArray(measurement.Level) && measurement.Level.length === 1 && measurement.Level[0] === -1);
    
    // 判断是否为异常（修复：正确处理数组类型的 Level）
    // 生长发育评估不需要标红，因为不存在不正常的发育
    const isGrowth = isGrowthMeasurement(measurement.Label);
    let isAbnormal = false;
    
    if (!isUndetected && measurement.Level !== undefined && !isGrowth) {
        if (Array.isArray(measurement.Level)) {
            // 数组类型：所有元素都是 0 才算正常，否则异常
            isAbnormal = !measurement.Level.every(level => level === 0);
        } else if (typeof measurement.Level === 'boolean') {
            // 布尔类型：false 为异常，true 为正常
            isAbnormal = measurement.Level === false;
        } else if (typeof measurement.Level === 'number') {
            // 数字类型：0 为正常，非 0 为异常
            isAbnormal = measurement.Level !== 0;
        }
    }
    
    if (isUndetected) {
        item.classList.add('undetected');
    } else if (isAbnormal) {
        item.classList.add('abnormal');
    }
    
    // 构建内容
    let content = `<div class="measurement-label">${getMeasurementLabel(measurement.Label)}</div>`;
    
    // 显示测量值（需同时检查 undefined 和 null）
    let valueText = '';
    if (measurement.Angle != null) {
        valueText = `${measurement.Angle.toFixed(2)}°`;
    } else if (measurement.U1_SN_Angle != null) {
        // U1_SN_Angle 的特殊字段名
        valueText = `${measurement.U1_SN_Angle.toFixed(2)}°`;
    } else if (measurement.Length_mm != null) {
        valueText = `${measurement.Length_mm.toFixed(2)} mm`;
    } else if (measurement.Length != null) {
        valueText = `${measurement.Length.toFixed(2)} mm`;
    } else if (measurement.Ratio != null) {
        valueText = `${measurement.Ratio.toFixed(2)}%`;
    } else if (measurement.Value != null) {
        valueText = measurement.Value.toFixed(2);
    } else if (measurement['PNS-UPW'] != null) {
        // 气道间隙特殊处理 - 显示全部5个测量值
        const airwayValues = [];
        if (measurement['PNS-UPW'] != null) {
            airwayValues.push(`PNS-UPW: ${measurement['PNS-UPW'].toFixed(2)}mm`);
        }
        if (measurement['SPP-SPPW'] != null) {
            airwayValues.push(`SPP-SPPW: ${measurement['SPP-SPPW'].toFixed(2)}mm`);
        }
        if (measurement['U-MPW'] != null) {
            airwayValues.push(`U-MPW: ${measurement['U-MPW'].toFixed(2)}mm`);
        }
        if (measurement['TB-YPPW'] != null) {
            airwayValues.push(`TB-YPPW: ${measurement['TB-YPPW'].toFixed(2)}mm`);
        }
        if (measurement['V-LPW'] != null) {
            airwayValues.push(`V-LPW: ${measurement['V-LPW'].toFixed(2)}mm`);
        }
        valueText = airwayValues.join(' | ');
    }
    
    if (valueText) {
        content += `<div class="measurement-value">${valueText}</div>`;
    }
    
    // 显示诊断结论
    if (measurement.Level !== undefined) {
        const conclusion = getMeasurementConclusion(measurement.Label, measurement.Level);
        if (conclusion) {
            content += `<div class="measurement-conclusion">${conclusion}</div>`;
        }
    }
    
    // 置信度已隐藏 - 不再显示测量数据的置信度
    
    item.innerHTML = content;
    
    // 若存在可视化指令，绑定点击渲染
    if (measurement.Visualization) {
        item.classList.add('clickable');
        item.onclick = () => handleMeasurementClick(measurement);
    }
    return item;
}

/**
 * 获取Level的文本描述
 * @param {string} label - 测量项标签
 * @param {number|boolean|Array} level - 等级
 * @returns {string} Level文本
 */
function getLevelText(label, level) {
    if (Array.isArray(level)) {
        return `[${level.join(', ')}]`;
    }
    
    if (typeof level === 'boolean') {
        return level ? '正常' : '异常';
    }
    
    if (typeof level === 'number') {
        if (label === 'ANB_Angle') {
            return `Level ${level} (${level === 0 ? '骨性I类' : level === 1 ? '骨性II类' : '骨性III类'})`;
        }
        return `Level ${level}`;
    }
    
    return '';
}

/**
 * 获取测量项标签
 * @param {string} label - 测量项标签
 * @returns {string} 显示正确的字段名（修正后端命名错误）
 * 
 * 修改说明：
 * - 大部分字段直接显示后端原始名称（便于排查）
 * - 仅修正已知的命名错误字段（保持JSON格式不变，只改前端显示）
 */
function getMeasurementLabel(label) {
    // 后端字段名已修正，前端直接显示即可
    // 保留此函数以备将来扩展
    return label;
}

/**
 * 获取测量项诊断结论
 * @param {string} label - 测量项标签
 * @param {number|boolean|Array|null} level - 等级，-1或null表示未检测
 * @returns {string} 诊断结论
 */
function getMeasurementConclusion(label, level) {
    // 未检测状态：Level === -1 或 null
    if (level === -1 || level === null) {
        return '未检测';
    }
    
    // 多选类型（如上下颌骨发育协调性）
    if (Array.isArray(level)) {
        // 未检测状态：Level === [-1]
        if (level.length === 1 && level[0] === -1) {
            return '未检测';
        }
        // Level: [0]=协调/正常; [1,0]=上颌过度-下颌正常 等
        const coordLabels = { 0: '正常', 1: '前突/过度', 2: '后缩/不足' };
        if (level.length === 1) {
            return level[0] === 0 ? '协调' : coordLabels[level[0]] || level[0];
        }
        return level.map(l => coordLabels[l] || l).join(' - ');
    }
    
    // 布尔类型（气道间隙、腺样体指数）
    if (typeof level === 'boolean') {
        if (label === 'Airway_Gap') {
            return level ? '正常' : '不足';
        } else if (label === 'Adenoid_Index') {
            return level ? '未见肿大' : '肿大';
        }
        return level ? '正常' : '异常';
    }
    
    // 数值类型
    if (typeof level === 'number') {
        // ㊳ 颈椎成熟度分期 (1-6)
        if (label === 'Cervical_Vertebral_Maturity_Stage') {
            const stages = ['', 'CVMS I期', 'CVMS II期', 'CVMS III期（生长高峰期）', 'CVMS IV期', 'CVMS V期', 'CVMS VI期'];
            return stages[level] || `CVMS ${level}期`;
        }
        
        // ① ANB角: 0=骨性I类; 1=骨性II类; 2=骨性III类
        if (label === 'ANB_Angle') {
            if (level === 0) return '骨性I类（正常）';
            if (level === 1) return '骨性II类（ANB>6°）';
            if (level === 2) return '骨性III类（ANB<2°）';
        }
        
        // ⑰ Wits分析: 0=骨性I类; 1=骨性II类; 2=骨性III类
        if (label === 'Distance_Witsmm') {
            if (level === 0) return '骨性I类';
            if (level === 1) return '骨性II类（>1.5mm）';
            if (level === 2) return '骨性III类（<-4.3mm）';
        }
        
        // ②③㊲ 颌骨长度: 0=正常; 1=发育过度; 2=发育不足
        if (label === 'PtmANS_Length' || label === 'GoPo_Length' || label === 'Go_Me_Length') {
            if (level === 0) return '正常';
            if (level === 1) return '发育过度';
            if (level === 2) return '发育不足';
        }
        
        // ④ 颏部发育量: 0=正常; 1=发育过度; 2=后缩
        if (label === 'PoNB_Length') {
            if (level === 0) return '正常';
            if (level === 1) return '发育过度（>2.5mm）';
            if (level === 2) return '后缩（<-0.5mm）';
        }
        
        // ⑥ 面部高度比例: 0=平均生长型; 1=水平生长型; 2=垂直生长型
        if (label === 'SGo_NMe_Ratio') {
            if (level === 0) return '平均生长型';
            if (level === 1) return '水平生长型（>71%）';
            if (level === 2) return '垂直生长型（<63%）';
        }
        
        // ㉗ Y轴角: 0=平均生长型; 1=水平生长型; 2=垂直生长型
        if (label === 'Y_Axis_Angle') {
            if (level === 0) return '平均生长型';
            if (level === 1) return '水平生长型';
            if (level === 2) return '垂直生长型';
        }
        
        // ⑦㉚ 下颌平面角/SN-MP角: 0=均角; 1=高角; 2=低角
        if (label === 'FH_MP_Angle' || label === 'SN_MP_Angle') {
            if (level === 0) return '均角';
            if (level === 1) return '高角（>33°）';
            if (level === 2) return '低角（<25°）';
        }
        
        // ⑧ 上切牙-SN角: 0=正常; 1=唇倾; 2=舌倾
        // 注意：阈值因性别和牙期而异（男性恒牙期 107±6°，女性恒牙期 105±6°）
        // 简化显示：不写具体数值，避免与实际阈值不符
        if (label === 'U1_SN_Angle') {
            if (level === 0) return '正常';
            if (level === 1) return '唇倾（数值偏大）';
            if (level === 2) return '舌倾（数值偏小）';
        }
        
        // ⑨㉑ 下切牙-下颌平面角: 0=正常; 1=唇倾; 2=舌倾
        if (label === 'IMPA_Angle') {
            if (level === 0) return '正常';
            if (level === 1) return '唇倾';
            if (level === 2) return '舌倾';
        }
        
        // ⑬⑮ SNA/SNB角: 0=正常; 1=前突; 2=后缩
        if (label === 'SNA_Angle' || label === 'SNB_Angle') {
            if (level === 0) return '正常';
            if (level === 1) return '前突';
            if (level === 2) return '后缩';
        }
        
        // ⑭ 上颌骨位置: 0=正常; 1=靠前; 2=靠后
        if (label === 'Upper_Jaw_Position') {
            if (level === 0) return '正常';
            if (level === 1) return '靠前（>20mm）';
            if (level === 2) return '靠后（<14mm）';
        }
        
        // ⑯ 下颌骨位置 (Pcd-S): 0=正常; 1=后缩; 2=前突
        // 注意：Pcd 是髁突后点（Posterior Condylion），位于 S 点后方
        // 距离测量：从蝶鞍点（S）到髁突后点（Pcd）
        // Level=1: 距离偏大 → 髁突位置过于靠后 → 下颌关节后移 → 下颌整体后缩
        // Level=2: 距离偏小 → 髁突位置过于靠前 → 下颌关节前移 → 下颌整体前突
        if (label === 'Pcd_Lower_Position') {
            if (level === 0) return '正常';
            if (level === 1) return '下颌后缩（S-髁突间距偏大，关节位置靠后）';
            if (level === 2) return '下颌前突（S-髁突间距偏小，关节位置靠前）';
        }
        
        // ⑲ 上切牙-NA角: 0=正常; 1=唇倾; 2=舌倾
        if (label === 'U1_NA_Angle') {
            if (level === 0) return '正常';
            if (level === 1) return '唇倾（>30°）';
            if (level === 2) return '舌倾（<18°）';
        }
        
        // ⑳ 上切牙突度: 0=正常; 1=前突; 2=后缩
        if (label === 'U1_NA_Incisor_Length') {
            if (level === 0) return '正常';
            if (level === 1) return '前突（>6mm）';
            if (level === 2) return '后缩（<2mm）';
        }
        
        // ㉒ FMIA角: 0=正常; 1=舌倾(增大); 2=唇倾(减小)
        if (label === 'FMIA_Angle') {
            if (level === 0) return '正常';
            if (level === 1) return '舌倾（>59°）';
            if (level === 2) return '唇倾（<45°）';
        }
        
        // ㉓ 下切牙-NB角: 0=正常; 1=唇倾; 2=舌倾
        if (label === 'L1_NB_Angle') {
            if (level === 0) return '正常';
            if (level === 1) return '唇倾（>38°）';
            if (level === 2) return '舌倾（<26°）';
        }
        
        // ㉔ 下切牙突度: 0=正常; 1=前突; 2=后缩
        if (label === 'L1_NB_Distance') {
            if (level === 0) return '正常';
            if (level === 1) return '前突（>10mm）';
            if (level === 2) return '后缩（<4mm）';
        }
        
        // ㉕ 上下切牙角: 0=正常; 1=减小; 2=增大
        if (label === 'U1_L1_Inter_Incisor_Angle') {
            if (level === 0) return '正常';
            if (level === 1) return '开唇露齿（>130°）';
            if (level === 2) return '深覆合趋势（<112°）';
        }
        
        // ㉗ 下颌生长方向角: 0=正常; 1=过度; 2=不足
        if (label === 'Mandibular_Growth_Angle') {
            if (level === 0) return '正常';
            if (level === 1) return '过度（>91°）';
            if (level === 2) return '不足（<83°）';
        }
        
        // ㉟ 下颌生长型角: 0=平均生长型; 1=顺时针生长型; 2=逆时针生长型
        if (label === 'Mandibular_Growth_Type_Angle') {
            if (level === 0) return '平均生长型';
            if (level === 1) return '顺时针生长型（>402°）';
            if (level === 2) return '逆时针生长型（<390°）';
        }
        
        // ㊱ 前颅底长度: 0=正常; 1=增大; 2=减小
        if (label === 'S_N_Anterior_Cranial_Base_Length') {
            if (level === 0) return '正常';
            if (level === 1) return '增大（>70.6mm）';
            if (level === 2) return '减小（<62.8mm）';
        }
        
        // ㉛㉜㉝㉞ 牙槽高度: 0=正常; 1=过大; 2=不足
        if (label === 'U1_PP_Upper_Anterior_Alveolar_Height' ||
            label === 'L1_MP_Lower_Anterior_Alveolar_Height' ||
            label === 'U6_PP_Upper_Posterior_Alveolar_Height' ||
            label === 'L6_MP_Lower_Posterior_Alveolar_Height') {
            if (level === 0) return '正常';
            if (level === 1) return '过大';
            if (level === 2) return '不足';
        }
        
        // 默认处理
        if (level === 0) {
            return '正常';
        } else if (level === 1) {
            return '异常（偏高/过度）';
        } else if (level === 2) {
            return '异常（偏低/不足）';
        }
    }
    
    return '';
}

/**
 * 判断是否为骨骼测量项
 * @param {string} label - 测量项标签
 * @returns {boolean} 是否为骨骼测量项
 */
function isBoneMeasurement(label) {
    const boneLabels = [
        // ① ANB角
        'ANB_Angle',
        // ② 上颌基骨长度
        'PtmANS_Length',
        // ③ 下颌体长度
        'GoPo_Length',
        // ④ 颏部发育量
        'PoNB_Length',
        // ⑤ 上下颌骨发育协调性
        'Jaw_Development_Coordination',
        // ⑬ SNA角
        'SNA_Angle',
        // ⑭ 上颌骨位置
        'Upper_Jaw_Position',
        // ⑮ SNB角
        'SNB_Angle',
        // ⑯ 下颌骨位置
        'Pcd_Lower_Position',
        // ⑰ Wits分析
        'Distance_Witsmm',
        // ㊱ 前颅底长度
        'S_N_Anterior_Cranial_Base_Length',
        // ㊲ 下颌体长度(重复)
        'Go_Me_Length'
    ];
    return boneLabels.includes(label);
}

/**
 * 判断是否为牙齿测量项
 * @param {string} label - 测量项标签
 * @returns {boolean} 是否为牙齿测量项
 */
function isToothMeasurement(label) {
    const toothLabels = [
        // ⑧ 上切牙-SN角
        'U1_SN_Angle',
        // ⑨ 下切牙-下颌平面角
        'IMPA_Angle',
        // ⑲ 上切牙-NA角
        'U1_NA_Angle',
        // ⑳ 上切牙突度
        'U1_NA_Incisor_Length',
        // ㉒ FMIA角
        'FMIA_Angle',
        // ㉓ 下切牙-NB角
        'L1_NB_Angle',
        // ㉔ 下切牙突度
        'L1_NB_Distance',
        // ㉕ 上下切牙角
        'U1_L1_Inter_Incisor_Angle',
        // ㉛ 上前牙槽高度
        'U1_PP_Upper_Anterior_Alveolar_Height',
        // ㉜ 下前牙槽高度
        'L1_MP_Lower_Anterior_Alveolar_Height',
        // ㉝ 上后牙槽高度
        'U6_PP_Upper_Posterior_Alveolar_Height',
        // ㉞ 下后牙槽高度
        'L6_MP_Lower_Posterior_Alveolar_Height'
    ];
    return toothLabels.includes(label);
}

/**
 * 判断是否为生长发育测量项
 * @param {string} label - 测量项标签
 * @returns {boolean} 是否为生长发育测量项
 */
function isGrowthMeasurement(label) {
    const growthLabels = [
        // ⑥ 面部高度比例
        'SGo_NMe_Ratio',
        // ⑦ 下颌平面角
        'FH_MP_Angle',
        // ㉗ Y轴角
        'Y_Axis_Angle',
        // ㉘ 下颌生长方向角
        'Mandibular_Growth_Angle',
        // ㉚ SN-MP角
        'SN_MP_Angle',
        // ㉟ 下颌生长型角
        'Mandibular_Growth_Type_Angle',
        // ㊴ 颈椎成熟度分期
        'Cervical_Vertebral_Maturity_Stage'
    ];
    return growthLabels.includes(label);
}

/**
 * 渲染全景片结果（支持图片和 DICOM）
 * @param {Object} data - 全景片分析数据
 */
async function renderPanoramic(data) {
    console.log('开始渲染全景片结果...', data);
    
    // 先显示主容器和报告区域（即使图片还没加载）
    const mainContainer = document.getElementById('mainContainer');
    if (mainContainer) {
        mainContainer.classList.remove('hidden');
    }
    
    // 生成结构化报告
    buildPanoReport(data);
    
    // ================= 修改开始：优先使用缓存的原始图片 =================
    // 1. 优先使用缓存的原始图片，否则从文件加载
    let img = appState.originalImage;
    
    if (!img) {
        const file = document.getElementById('imageFile').files[0];
        if (!file) {
            // 如果也没有文件输入，且没有缓存，则无法渲染
            console.error('未找到文件');
            if (!appState.originalImage) {
                displayError({ displayMessage: '未找到上传的文件' });
                return;
            }
        } else {
            console.log('找到文件:', file.name, '大小:', file.size);
            try {
                img = await new Promise((resolve, reject) => {
                    const image = new Image();
                    image.onload = () => resolve(image);
                    image.onerror = reject;
                    image.src = URL.createObjectURL(file);
                });
            } catch (error) {
                console.error('文件加载失败:', error);
                displayError({ displayMessage: '文件加载失败' });
                return;
            }
        }
    }
    // ================= 修改结束 =================
    
    console.log('图像加载成功，尺寸:', img.width, 'x', img.height);
    
    // 3. 获取容器尺寸，计算缩放比例以适应容器
    const container = document.getElementById('imageContainer');
    if (!container) {
        console.error('图像容器不存在');
        return;
    }
    
    const containerWidth = container.clientWidth;
    const containerHeight = container.clientHeight;
    
    console.log('容器尺寸:', containerWidth, 'x', containerHeight);
    
    // 计算缩放比例
    let scale = 1.0;
    let displayWidth = img.width;
    let displayHeight = img.height;
    
    if (containerWidth > 0 && containerHeight > 0) {
        const scaleX = containerWidth / img.width;
        const scaleY = containerHeight / img.height;
        scale = Math.min(scaleX, scaleY, 1.0); // 不放大，只缩小
        displayWidth = img.width * scale;
        displayHeight = img.height * scale;
    }
    
    console.log('缩放比例:', scale, '显示尺寸:', displayWidth, 'x', displayHeight);
    
    // 保存缩放比例
    appState.imageScale = scale;
    appState.originalImage = img;
    
    // 4. 初始化 Konva Stage
    const stage = initKonvaStage('imageContainer', displayWidth, displayHeight);
    if (!stage) {
        console.error('Konva Stage 初始化失败');
        return;
    }
    
    // 5. 创建背景图层并添加图片
    const bgLayer = new Konva.Layer();
    const bgImage = new Konva.Image({
        x: 0,
        y: 0,
        image: img,
        width: displayWidth,
        height: displayHeight
    });
    bgLayer.add(bgImage);
    stage.add(bgLayer);
    appState.konvaLayers.background = bgLayer;
    
    // 6. 绘制牙齿分割区域
    drawToothSegments(data, stage, scale);
    
    // 7. 绘制区域性发现（种植体、密度影等）
    drawRegionalFindings(data, stage, scale);
    
    // 绘制画布
    stage.draw();
    
    // 8. 初始化图层控制面板
    initLayerControlPanel();
    
    console.log('全景片渲染完成');
}

/**
 * 绘制牙齿分割区域
 * @param {Object} data - 全景片分析数据
 * @param {Konva.Stage} stage - Konva Stage 实例
 * @param {number} scale - 缩放比例
 */
function drawToothSegments(data, stage, scale) {
    // 创建牙齿分割图层
    const toothLayer = new Konva.Layer();
    
    // 遍历 ToothAnalysis 数组，绘制分割区域
    if (data.ToothAnalysis && Array.isArray(data.ToothAnalysis)) {
        console.log('开始绘制牙齿分割区域，总数:', data.ToothAnalysis.length);
        
        let drawnCount = 0;
        data.ToothAnalysis.forEach(tooth => {
            // 检查是否有分割掩码数据
            if (!tooth.SegmentationMask || !tooth.SegmentationMask.Coordinates) {
                return;
            }
            
            const coords = tooth.SegmentationMask.Coordinates;
            
            // 检查坐标数据格式
            if (!Array.isArray(coords) || coords.length === 0) {
                return;
            }
            
            // 将坐标数组转换为 Konva.Line 需要的格式
            // 输入格式: [[x1, y1], [x2, y2], ...]
            // 输出格式: [x1, y1, x2, y2, ...]
            let points = [];
            for (let i = 0; i < coords.length; i++) {
                const point = coords[i];
                if (Array.isArray(point) && point.length >= 2) {
                    // 应用缩放比例
                    points.push(point[0] * scale);
                    points.push(point[1] * scale);
                }
            }
            
            // 如果点数不足（至少需要3个点才能形成多边形），跳过
            if (points.length < 6) {
                return;
            }
            
            // ----------------------------------------------------
            // 优化步骤 1: RDP 抽稀 (关键步骤！去除阶梯状像素点)
            // tolerance = 1.5 ~ 2.5 之间效果最好。
            // 值越小保留细节越多但锯齿越多，值越大线条越直但可能变形。
            // ----------------------------------------------------
            points = simplifyPoints(points, 2.0, true);
            
            // ----------------------------------------------------
            // 优化步骤 2: Chaikin 平滑
            // 在 RDP 把它变直后，再用 Chaikin 把角变圆
            // ----------------------------------------------------
            points = smoothPolyline(points, 3); // 迭代次数 3 次通常足够了
            
            // 创建多边形线条（使用圆润的线条样式）
            const line = new Konva.Line({
                points: points,
                closed: true,
                stroke: '#C084FC',
                strokeWidth: CONFIG.STROKE_WIDTH,
                fill: 'transparent',
                lineCap: 'round',      // 线条端点圆润
                lineJoin: 'round',     // 线条连接点圆润
                // ----------------------------------------------------
                // 优化步骤 3: 调整 Tension
                // 既然使用了 Chaikin 预处理，Tension 应该设为 0 或者很小(0.1)
                // 否则 Konva 会尝试在已经平滑的点之间再次插值，导致奇怪的扭曲
                // ----------------------------------------------------
                tension: 0,
                strokeScaleEnabled: false // 禁止线条随缩放变粗
            });
            
            // 存储牙齿信息到 line 对象，用于后续 Tooltip
            line.toothData = tooth;
            
            // 绑定 Tooltip 事件
            line.on('mouseenter', function(e) {
                showToothTooltip(this, this.toothData, e);
            });
            
            line.on('mouseleave', function() {
                hideTooltip();
            });
            
            // 添加点击切换图层显示/隐藏功能
            addClickToggleToNode(line, 'toothSegments');
            
            toothLayer.add(line);
            drawnCount++;
        });
        
        console.log('牙齿分割区域绘制完成，已绘制:', drawnCount, '个');
    } else {
        console.warn('未找到牙齿分析数据，data.ToothAnalysis:', data.ToothAnalysis);
    }
    
    stage.add(toothLayer);
    appState.konvaLayers.toothSegments = toothLayer;
}

/**
 * 绘制区域性发现（种植体、根尖密度影、髁突等）
 * 将不同类型的发现绘制到独立的图层中
 * @param {Object} data - 全景片分析数据
 * @param {Konva.Stage} stage - Konva Stage 实例
 * @param {number} scale - 缩放比例
 */
function drawRegionalFindings(data, stage, scale) {
    // 1. 种植体图层
    const implantLayer = new Konva.Layer();
    let implantCount = 0;
    
    if (data.ImplantAnalysis && data.ImplantAnalysis.Items && Array.isArray(data.ImplantAnalysis.Items)) {
        console.log('开始绘制种植体，总数:', data.ImplantAnalysis.Items.length);
        
        data.ImplantAnalysis.Items.forEach(implant => {
            // 检查边界框数据
            if (!implant.BBox || !Array.isArray(implant.BBox) || implant.BBox.length < 4) {
                return;
            }
            
            const bbox = implant.BBox; // [x1, y1, x2, y2]
            
            // 应用缩放比例
            const x = bbox[0] * scale;
            const y = bbox[1] * scale;
            const width = (bbox[2] - bbox[0]) * scale;
            const height = (bbox[3] - bbox[1]) * scale;
            
            // 创建矩形
            const rect = new Konva.Rect({
                x: x,
                y: y,
                width: width,
                height: height,
                stroke: 'blue',
                strokeWidth: CONFIG.STROKE_WIDTH,
                fill: 'transparent'
            });
            
            // 存储发现数据到 rect 对象，用于后续 Tooltip
            rect.findingData = implant;
            rect.findingType = 'implant';
            
            // 绑定 Tooltip 事件
            rect.on('mouseenter', function(e) {
                showFindingTooltip(this, this.findingData, e);
            });
            
            rect.on('mouseleave', function() {
                hideTooltip();
            });
            
            // 添加点击切换图层显示/隐藏功能
            addClickToggleToNode(rect, 'implants');
            
            implantLayer.add(rect);
            implantCount++;
        });
        
        console.log('种植体绘制完成，已绘制:', implantCount, '个');
    }
    
    if (implantCount > 0) {
        stage.add(implantLayer);
        appState.konvaLayers.implants = implantLayer;
    }
    
    // 2. 根尖密度影图层
    const densityLayer = new Konva.Layer();
    let densityCount = 0;
    
    if (data.RootTipDensityAnalysis && data.RootTipDensityAnalysis.Items && Array.isArray(data.RootTipDensityAnalysis.Items)) {
        console.log('开始绘制根尖密度影，总数:', data.RootTipDensityAnalysis.Items.length);
        
        data.RootTipDensityAnalysis.Items.forEach(density => {
            // 检查边界框数据
            if (!density.BBox || !Array.isArray(density.BBox) || density.BBox.length < 4) {
                return;
            }
            
            const bbox = density.BBox; // [x1, y1, x2, y2]
            
            // 应用缩放比例
            const x = bbox[0] * scale;
            const y = bbox[1] * scale;
            const width = (bbox[2] - bbox[0]) * scale;
            const height = (bbox[3] - bbox[1]) * scale;
            
            // 创建矩形（虚线样式）
            const rect = new Konva.Rect({
                x: x,
                y: y,
                width: width,
                height: height,
                stroke: 'yellow',
                strokeWidth: CONFIG.STROKE_WIDTH,
                dash: [5, 5], // 虚线
                fill: 'transparent'
            });
            
            // 存储发现数据到 rect 对象，用于后续 Tooltip
            rect.findingData = density;
            rect.findingType = 'density';
            
            // 绑定 Tooltip 事件
            rect.on('mouseenter', function(e) {
                showFindingTooltip(this, this.findingData, e);
            });
            
            rect.on('mouseleave', function() {
                hideTooltip();
            });
            
            // 添加点击切换图层显示/隐藏功能
            addClickToggleToNode(rect, 'density');
            
            densityLayer.add(rect);
            densityCount++;
        });
        
        console.log('根尖密度影绘制完成，已绘制:', densityCount, '个');
    }
    
    if (densityCount > 0) {
        stage.add(densityLayer);
        appState.konvaLayers.density = densityLayer;
    }
    
    // 3. 髁突图层
    const condyleLayer = new Konva.Layer();
    let condyleCount = 0;
    
    // 绘制髁突区域（来自 AnatomyResults 多边形坐标）
    if (Array.isArray(data.AnatomyResults) && data.AnatomyResults.length > 0) {
        // 获取髁突诊断信息
        let leftCondyleInfo = null;
        let rightCondyleInfo = null;
        if (data.JointAndMandible && data.JointAndMandible.CondyleAssessment) {
            const assessment = data.JointAndMandible.CondyleAssessment;
            leftCondyleInfo = assessment.condyle_Left || null;
            rightCondyleInfo = assessment.condyle_Right || null;
        }
        
        data.AnatomyResults.forEach(item => {
            const seg = item.SegmentationMask || {};
            const rawLabel = ((item.Label || seg.Label) || '').toLowerCase();
            // 仅处理髁突
            if (!rawLabel.includes('condyle')) return;
            
            // 判定左右
            let side = null;
            if (rawLabel.includes('left')) side = 'left';
            else if (rawLabel.includes('right') || rawLabel.includes('righ')) side = 'right';
            
            if (!side) return;
            
            const mask = item.SegmentationMask || item;
            const coords = mask.Coordinates;
            if (!coords) return;
            
            // 选择诊断信息和配色
            const info = side === 'left' ? leftCondyleInfo : rightCondyleInfo;
            let strokeColor = 'purple';
            let fillColor = 'rgba(128,0,128,0.20)';
            if (info) {
                if (info.Morphology === 0) { // 正常
                    strokeColor = 'green';
                    fillColor = 'rgba(0,128,0,0.25)';
                } else if (info.Morphology === 1) { // 吸收
                    strokeColor = 'orange';
                    fillColor = 'rgba(255,165,0,0.25)';
                }
            }
            
            // 归一化坐标，支持多边形/多多边形/矩形
            const polys = normalizeMaskPolygons(coords, scale);
            if (polys.length > 0) {
                polys.forEach(pArr => {
                    // ============================================================
                    // 针对髁突的 3 步优化处理（与下颌分支一致）
                    // ============================================================
                    
                    // 1. 【去毛刺】滑动平均 (新增步骤)
                    // windowSize = 5：髁突较大，可以用 5 甚至 7 来强力去除突出的像素点
                    let pts = movingAverageSmooth(pArr, 5);

                    // 2. 【去阶梯】RDP 抽稀
                    // tolerance = 2.5：髁突轮廓平缓，可以适当加大容差，让线条更直
                    pts = simplifyPoints(pts, 2.5, true);

                    // 3. 【变圆润】Chaikin 平滑
                    // 迭代 3-4 次，让转折处非常圆滑
                    pts = smoothPolyline(pts, 4);

                    const poly = new Konva.Line({
                        points: pts,
                        closed: true,
                        stroke: strokeColor,
                        strokeWidth: CONFIG.STROKE_WIDTH,
                        lineCap: 'round',
                        lineJoin: 'round',
                        // 经过上面三步，点已经很顺滑了，tension 设为 0 即可，
                        // 也可以尝试 0.1 给一点点弹性，但不要太大，否则容易产生波浪
                        tension: 0,
                        fill: fillColor,
                        // 移除阴影效果，让线条更细、更清晰
                        // shadowColor: strokeColor,
                        // shadowBlur: 6,
                        // shadowOpacity: 0.6,
                        strokeScaleEnabled: false // 禁止线条随缩放变粗
                    });
                    poly.findingType = 'condyle';
                    poly.findingData = info;
                    poly.condyleSide = side;
                    poly.on('mouseenter', function(e) { showCondyleTooltip(this, info, side, e); });
                    poly.on('mouseleave', function() { hideTooltip(); });
                    // 添加点击切换图层显示/隐藏功能
                    addClickToggleToNode(poly, 'condyle');
                    condyleLayer.add(poly);
                    condyleCount++;
                });
            }
        });
        
        console.log('髁突区域绘制完成，已绘制:', condyleCount, '个');
    }
    
    if (condyleCount > 0) {
        stage.add(condyleLayer);
        appState.konvaLayers.condyle = condyleLayer;
    }
    
    // 4. 下颌升支图层
    const mandibleLayer = new Konva.Layer();
    let mandibleCount = 0;
    
    // 绘制下颌分支区域（来自 AnatomyResults 多边形坐标）
    if (Array.isArray(data.AnatomyResults) && data.AnatomyResults.length > 0) {
        // 获取下颌骨对称性信息
        let mandibleSymmetryInfo = null;
        if (data.JointAndMandible) {
            mandibleSymmetryInfo = {
                RamusSymmetry: data.JointAndMandible.RamusSymmetry,
                GonialAngleSymmetry: data.JointAndMandible.GonialAngleSymmetry,
                Detail: data.JointAndMandible.Detail,
                Confidence: data.JointAndMandible.Confidence
            };
        }
        
        data.AnatomyResults.forEach(item => {
            const seg = item.SegmentationMask || {};
            const rawLabel = ((item.Label || seg.Label) || '').toLowerCase();
            // 仅处理下颌分支
            if (!rawLabel.includes('mandible')) return;
            
            // 判定左右
            let side = null;
            if (rawLabel.includes('left')) side = 'left';
            else if (rawLabel.includes('right') || rawLabel.includes('righ')) side = 'right';
            
            if (!side) return;
            
            const mask = item.SegmentationMask || item;
            const coords = mask.Coordinates;
            if (!coords) return;
            
            // 选择配色（使用蓝色系来区分下颌分支）
            let strokeColor = 'cyan';
            let fillColor = 'rgba(0,255,255,0.25)';  // 增加透明度，确保鼠标事件能触发
            
            // 根据对称性信息调整颜色（如果不对称，使用橙色）
            if (mandibleSymmetryInfo) {
                if (mandibleSymmetryInfo.RamusSymmetry === false || mandibleSymmetryInfo.GonialAngleSymmetry === false) {
                    strokeColor = 'orange';
                    fillColor = 'rgba(255,165,0,0.25)';  // 增加透明度
                }
            }
            
            // 归一化坐标，支持多边形/多多边形/矩形
            const polys = normalizeMaskPolygons(coords, scale);
            if (polys.length > 0) {
                polys.forEach(pArr => {
                    // ============================================================
                    // 针对下颌升支的 3 步优化处理
                    // ============================================================
                    
                    // 1. 【去毛刺】滑动平均 (新增步骤)
                    // windowSize = 5：下颌骨较大，可以用 5 甚至 7 来强力去除突出的像素点
                    let pts = movingAverageSmooth(pArr, 5);

                    // 2. 【去阶梯】RDP 抽稀
                    // tolerance = 2.5：下颌骨轮廓平缓，可以适当加大容差，让线条更直
                    pts = simplifyPoints(pts, 2.5, true);

                    // 3. 【变圆润】Chaikin 平滑
                    // 迭代 3-4 次，让转折处非常圆滑
                    pts = smoothPolyline(pts, 4);

                    const poly = new Konva.Line({
                        points: pts,
                        closed: true,
                        stroke: strokeColor,
                        strokeWidth: CONFIG.STROKE_WIDTH,
                        lineCap: 'round',
                        lineJoin: 'round',
                        // 经过上面三步，点已经很顺滑了，tension 设为 0 即可，
                        // 也可以尝试 0.1 给一点点弹性，但不要太大，否则容易产生波浪
                        tension: 0,
                        fill: fillColor,
                        // 移除阴影效果，让线条更细、更清晰
                        // shadowColor: strokeColor,
                        // shadowBlur: 6,
                        // shadowOpacity: 0.6,
                        listening: true,  // 确保事件监听启用
                        perfectDrawEnabled: false,  // 优化性能
                        strokeScaleEnabled: false // 禁止线条随缩放变粗
                    });
                    poly.findingType = 'mandible';
                    poly.findingData = mandibleSymmetryInfo;
                    poly.mandibleSide = side;
                    
                    // 绑定鼠标事件
                    poly.on('mouseenter', function(e) {
                        console.log('Mandible mouseenter triggered', side, mandibleSymmetryInfo);
                        showMandibleTooltip(this, mandibleSymmetryInfo, side, e);
                    });
                    poly.on('mouseleave', function() {
                        console.log('Mandible mouseleave triggered');
                        hideTooltip();
                    });
                    
                    // 添加鼠标样式
                    poly.on('mouseenter', function() {
                        document.body.style.cursor = 'pointer';
                    });
                    poly.on('mouseleave', function() {
                        document.body.style.cursor = 'default';
                    });
                    
                    // 添加点击切换图层显示/隐藏功能
                    addClickToggleToNode(poly, 'mandible');
                    
                    mandibleLayer.add(poly);
                    mandibleCount++;
                });
            }
        });
        
        console.log('下颌分支区域绘制完成，已绘制:', mandibleCount, '个');
    }
    
    if (mandibleCount > 0) {
        stage.add(mandibleLayer);
        appState.konvaLayers.mandible = mandibleLayer;
    }
    
    // 5. 上颌窦图层
    const sinusLayer = new Konva.Layer();
    let sinusCount = 0;
    
    // 绘制上颌窦区域（来自 AnatomyResults 多边形坐标）
    if (Array.isArray(data.AnatomyResults) && data.AnatomyResults.length > 0) {
        // 获取上颌窦诊断信息
        let sinusInfoMap = {};
        if (data.MaxillarySinus && Array.isArray(data.MaxillarySinus)) {
            data.MaxillarySinus.forEach(sinusData => {
                sinusInfoMap[sinusData.Side] = sinusData;
            });
        }
        
        data.AnatomyResults.forEach(item => {
            const seg = item.SegmentationMask || {};
            const rawLabel = ((item.Label || seg.Label) || '').toLowerCase();
            // 仅处理上颌窦
            if (!rawLabel.includes('sinus')) return;
            
            // 判定左右
            let side = null;
            if (rawLabel.includes('left')) side = 'left';
            else if (rawLabel.includes('right') || rawLabel.includes('righ')) side = 'right';
            
            if (!side) return;
            
            const mask = item.SegmentationMask || item;
            const coords = mask.Coordinates;
            if (!coords) return;
            
            // 获取对应侧的诊断信息
            const sinusInfo = sinusInfoMap[side] || null;
            
            // =========== 修改开始 ===========
            
            // 默认颜色修改为：鲜艳的浅绿色
            let strokeColor = '#55efc4';  
            let fillColor = 'rgba(85, 239, 196, 0.25)'; // 对应的半透明填充颜色
            
            if (sinusInfo) {
                if (sinusInfo.Inflammation === true) {
                    // 有炎症：保持橙红色警示 (医学上通常需要保留这个区分)
                    strokeColor = '#E67E22';
                    fillColor = 'rgba(230, 126, 34, 0.30)';
                } else if (sinusInfo.Pneumatization === 3) {
                    // III型过度气化：保持黄色警示
                    strokeColor = '#F1C40F';
                    fillColor = 'rgba(241, 196, 15, 0.25)';
                } else if (sinusInfo.Pneumatization === 2) {
                    // II型显著气化：保持浅黄色提示
                    strokeColor = '#F39C12';
                    fillColor = 'rgba(243, 156, 18, 0.20)';
                } else {
                    // 正常/无炎症：强制使用鲜艳浅绿色
                    strokeColor = '#55efc4';
                    fillColor = 'rgba(85, 239, 196, 0.25)';
                }
            }
            
            // =========== 修改结束 ===========
            
            // 归一化坐标，支持多边形/多多边形/矩形
            const polys = normalizeMaskPolygons(coords, scale);
            if (polys.length > 0) {
                polys.forEach(pArr => {
                    // 记得应用之前的优化：先抽稀(2步) -> 再平滑(3步)
                    let pts = simplifyPoints(pArr, 2.0, true); // 抽稀
                    pts = smoothPolyline(pts, 3);              // 平滑

                    const poly = new Konva.Line({
                        points: pts,
                        closed: true,
                        stroke: strokeColor,
                        strokeWidth: CONFIG.STROKE_WIDTH,
                        lineCap: 'round',
                        lineJoin: 'round',
                        tension: 0, // 记得设为0
                        fill: fillColor,
                        
                        // 记得：如果你希望线条锐利，不要加 shadowBlur
                        // shadowColor: strokeColor,
                        // shadowBlur: 6,
                        
                        listening: true,
                        perfectDrawEnabled: false,
                        strokeScaleEnabled: false // 禁止线条随缩放变粗
                    });
                    poly.findingType = 'sinus';
                    poly.findingData = sinusInfo;
                    poly.sinusSide = side;
                    
                    // 绑定鼠标事件
                    poly.on('mouseenter', function(e) {
                        console.log('Sinus mouseenter triggered', side, sinusInfo);
                        showSinusTooltip(this, sinusInfo, side, e);
                    });
                    poly.on('mouseleave', function() {
                        console.log('Sinus mouseleave triggered');
                        hideTooltip();
                    });
                    
                    // 添加鼠标样式
                    poly.on('mouseenter', function() {
                        document.body.style.cursor = 'pointer';
                    });
                    poly.on('mouseleave', function() {
                        document.body.style.cursor = 'default';
                    });
                    
                    // 添加点击切换图层显示/隐藏功能
                    addClickToggleToNode(poly, 'sinus');
                    
                    sinusLayer.add(poly);
                    sinusCount++;
                });
            }
        });
        
        console.log('上颌窦区域绘制完成，已绘制:', sinusCount, '个');
    }
    
    if (sinusCount > 0) {
        stage.add(sinusLayer);
        appState.konvaLayers.sinus = sinusLayer;
    }
}

/**
 * 创建髁突矩形
 * @param {Object} maskData - 掩码数据
 * @param {number} scale - 缩放比例
 * @param {string} side - 侧别 ('left' 或 'right')
 * @param {Object|null} condyleInfo - 髁突诊断信息
 * @returns {Konva.Rect|null} 矩形对象或 null
 */
function createCondyleRect(maskData, scale, side, condyleInfo) {
    if (!maskData.Coordinates || !Array.isArray(maskData.Coordinates) || maskData.Coordinates.length < 4) {
        return null;
    }
    
    const coords = maskData.Coordinates; // [x1, y1, x2, y2]
    
    // 应用缩放比例
    const x = coords[0] * scale;
    const y = coords[1] * scale;
    const width = (coords[2] - coords[0]) * scale;
    const height = (coords[3] - coords[1]) * scale;
    
    // 根据诊断结果选择颜色：正常=绿色，吸收=橙色
    let strokeColor = 'purple';
    if (condyleInfo) {
        if (condyleInfo.Morphology === 0) {
            strokeColor = 'green';  // 正常
        } else if (condyleInfo.Morphology === 1) {
            strokeColor = 'orange'; // 吸收
        }
    }
    
    // 创建矩形（紫色/绿色/橙色表示髁突）
    const rect = new Konva.Rect({
        x: x,
        y: y,
        width: width,
        height: height,
        stroke: strokeColor,
        strokeWidth: CONFIG.STROKE_WIDTH,
        fill: 'transparent'
    });
    
    // 存储发现数据（反转左右显示）
    rect.findingData = condyleInfo || { Detail: `${side === 'left' ? '右' : '左'}侧髁突`, Confidence: 0.95 };
    rect.findingType = 'condyle';
    rect.condyleSide = side;
    
    return rect;
}

/**
 * 显示下颌分支 Tooltip
 * @param {Konva.Node} node - Konva 节点（Line）
 * @param {Object|null} mandibleInfo - 下颌骨对称性信息
 * @param {string} side - 侧别 ('left' 或 'right')
 * @param {Object} event - Konva 事件对象
 */
function showMandibleTooltip(node, mandibleInfo, side, event) {
    // 移除已存在的 Tooltip
    hideTooltip();
    
    // 创建 Tooltip 元素
    const tooltip = document.createElement('div');
    tooltip.id = 'findingTooltip';
    tooltip.className = 'tooltip';
    
    // 构建 Tooltip 内容（反转左右显示）
    const sideName = side === 'left' ? '右' : '左';
    let content = `<strong>${sideName}侧下颌分支</strong><br>`;
    
    if (mandibleInfo) {
        // 升支对称性
        if (mandibleInfo.RamusSymmetry !== undefined) {
            const ramusText = mandibleInfo.RamusSymmetry ? '对称' : '不对称';
            content += `升支对称性: ${ramusText}<br>`;
        }
        
        // 下颌角对称性
        if (mandibleInfo.GonialAngleSymmetry !== undefined) {
            const gonialText = mandibleInfo.GonialAngleSymmetry ? '对称' : '不对称';
            content += `下颌角对称性: ${gonialText}<br>`;
        }
        
        // 详细描述
        if (mandibleInfo.Detail) {
            content += `${mandibleInfo.Detail}<br>`;
        }
        
        // 置信度
        if (mandibleInfo.Confidence !== undefined) {
            content += `置信度: ${(mandibleInfo.Confidence * 100).toFixed(1)}%`;
        }
    } else {
        content += '诊断信息未找到';
    }
    
    tooltip.innerHTML = content;
    
    // 获取 Stage 的位置
    const stage = node.getStage();
    const stageBox = stage.container().getBoundingClientRect();
    
    // 获取节点在 Stage 中的位置（多边形的中心点）
    const points = node.points();
    let sumX = 0, sumY = 0, pointCount = 0;
    for (let i = 0; i < points.length; i += 2) {
        sumX += points[i];
        sumY += points[i + 1];
        pointCount++;
    }
    const centerX = sumX / pointCount;
    const centerY = sumY / pointCount;
    
    // 计算 Tooltip 位置（相对于页面）
    const tooltipX = stageBox.left + centerX + 15;
    const tooltipY = stageBox.top + centerY - 10;
    
    // 设置 Tooltip 位置
    tooltip.style.left = tooltipX + 'px';
    tooltip.style.top = tooltipY + 'px';
    
    // 添加到页面
    document.body.appendChild(tooltip);
    
    // 调整位置，确保不超出视口
    const tooltipRect = tooltip.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    
    if (tooltipRect.right > viewportWidth) {
        tooltip.style.left = (tooltipX - tooltipRect.width - 30) + 'px';
    }
    
    if (tooltipRect.bottom > viewportHeight) {
        tooltip.style.top = (tooltipY - tooltipRect.height) + 'px';
    }
    
    if (tooltipRect.left < 0) {
        tooltip.style.left = '10px';
    }
    
    if (tooltipRect.top < 0) {
        tooltip.style.top = '10px';
    }
}

/**
 * 显示髁突 Tooltip
 * @param {Konva.Node} node - Konva 节点（Rect）
 * @param {Object|null} condyleInfo - 髁突诊断信息
 * @param {string} side - 侧别 ('left' 或 'right')
 * @param {Object} event - Konva 事件对象
 */
function showCondyleTooltip(node, condyleInfo, side, event) {
    // 移除已存在的 Tooltip
    hideTooltip();
    
    // 创建 Tooltip 元素
    const tooltip = document.createElement('div');
    tooltip.id = 'findingTooltip';
    tooltip.className = 'tooltip';
    
    // 构建 Tooltip 内容（反转左右显示）
    const sideName = side === 'left' ? '右' : '左';
    let content = `<strong>${sideName}侧髁突</strong><br>`;
    
    if (condyleInfo) {
        // 形态
        const morphologyText = condyleInfo.Morphology === 0 ? '正常' : '吸收';
        content += `形态: ${morphologyText}<br>`;
        
        // 详细描述
        if (condyleInfo.Detail) {
            content += `${condyleInfo.Detail}<br>`;
        }
        
        // 置信度
        if (condyleInfo.Confidence !== undefined) {
            content += `置信度: ${(condyleInfo.Confidence * 100).toFixed(1)}%`;
        }
    } else {
        content += '诊断信息未找到';
    }
    
    tooltip.innerHTML = content;
    
    // 获取 Stage 的位置
    const stage = node.getStage();
    const stageBox = stage.container().getBoundingClientRect();
    
    // 获取节点在 Stage 中的位置（矩形的中心点）
    const nodePos = node.getAbsolutePosition();
    const centerX = nodePos.x + node.width() / 2;
    const centerY = nodePos.y + node.height() / 2;
    
    // 计算 Tooltip 位置（相对于页面）
    const tooltipX = stageBox.left + centerX + 15;
    const tooltipY = stageBox.top + centerY - 10;
    
    // 设置 Tooltip 位置
    tooltip.style.left = tooltipX + 'px';
    tooltip.style.top = tooltipY + 'px';
    
    // 添加到页面
    document.body.appendChild(tooltip);
    
    // 调整位置，确保不超出视口
    const tooltipRect = tooltip.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    
    if (tooltipRect.right > viewportWidth) {
        tooltip.style.left = (tooltipX - tooltipRect.width - 30) + 'px';
    }
    
    if (tooltipRect.bottom > viewportHeight) {
        tooltip.style.top = (tooltipY - tooltipRect.height) + 'px';
    }
    
    if (tooltipRect.left < 0) {
        tooltip.style.left = '10px';
    }
    
    if (tooltipRect.top < 0) {
        tooltip.style.top = '10px';
    }
}

/**
 * 显示上颌窦 Tooltip
 * @param {Konva.Shape} node - Konva 节点
 * @param {Object|null} sinusInfo - 上颌窦诊断信息
 * @param {string} side - 侧别 ('left' 或 'right')
 * @param {Event} event - 鼠标事件
 */
function showSinusTooltip(node, sinusInfo, side, event) {
    // 移除已存在的 Tooltip
    hideTooltip();
    
    // 创建 Tooltip 元素
    const tooltip = document.createElement('div');
    tooltip.id = 'findingTooltip';
    tooltip.className = 'tooltip';
    
    // 构建 Tooltip 内容（反转左右显示）
    const sideName = side === 'left' ? '右' : '左';
    let content = `<strong>${sideName}上颌窦</strong><br>`;
    
    if (sinusInfo) {
        // 气化程度（按医学分型标准）
        // Ⅰ型: 正常/未气化 (距离>3mm)
        // Ⅱ型: 显著气化 (0-3mm)
        // Ⅲ型: 过度气化 (距离<0mm，牙根进入窦内)
        let pneumatizationText = 'Ⅰ型（正常）';
        if (sinusInfo.Pneumatization === 2) {
            pneumatizationText = 'Ⅱ型（显著气化）';
        } else if (sinusInfo.Pneumatization === 3) {
            pneumatizationText = 'Ⅲ型（过度气化）';
        }
        content += `气化程度: ${pneumatizationText}<br>`;
        
        // 炎症状态
        const inflammationText = sinusInfo.Inflammation ? '有炎症' : '无炎症';
        const inflammationStyle = sinusInfo.Inflammation ? 'color: #E74C3C; font-weight: bold;' : '';
        content += `炎症状态: <span style="${inflammationStyle}">${inflammationText}</span><br>`;
        
        // 分类
        if (sinusInfo.TypeClassification !== undefined && sinusInfo.TypeClassification !== 0) {
            content += `分类: Type ${sinusInfo.TypeClassification}<br>`;
        }
        
        // 牙根进入上颌窦
        if (sinusInfo.RootEntryToothFDI && sinusInfo.RootEntryToothFDI.length > 0) {
            content += `牙根进入: ${sinusInfo.RootEntryToothFDI.join(', ')}<br>`;
        }
        
        // 详细描述
        if (sinusInfo.Detail) {
            content += `<span style="font-size: 11px; color: #888;">${sinusInfo.Detail}</span><br>`;
        }
        
        // 置信度
        if (sinusInfo.Confidence_Inflammation !== undefined) {
            content += `置信度: ${(sinusInfo.Confidence_Inflammation * 100).toFixed(1)}%`;
        }
    } else {
        content += '诊断信息未找到';
    }
    
    tooltip.innerHTML = content;
    
    // 获取 Stage 的位置
    const stage = node.getStage();
    const stageBox = stage.container().getBoundingClientRect();
    
    // 获取节点在 Stage 中的位置（多边形的中心点）
    const points = node.points();
    let sumX = 0, sumY = 0, pointCount = 0;
    for (let i = 0; i < points.length; i += 2) {
        sumX += points[i];
        sumY += points[i + 1];
        pointCount++;
    }
    const centerX = sumX / pointCount;
    const centerY = sumY / pointCount;
    
    // 计算 Tooltip 位置（相对于页面）
    const tooltipX = stageBox.left + centerX + 15;
    const tooltipY = stageBox.top + centerY - 10;
    
    // 设置 Tooltip 位置
    tooltip.style.left = tooltipX + 'px';
    tooltip.style.top = tooltipY + 'px';
    
    // 添加到页面
    document.body.appendChild(tooltip);
    
    // 调整位置，确保不超出视口
    const tooltipRect = tooltip.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    
    if (tooltipRect.right > viewportWidth) {
        tooltip.style.left = (tooltipX - tooltipRect.width - 30) + 'px';
    }
    
    if (tooltipRect.bottom > viewportHeight) {
        tooltip.style.top = (tooltipY - tooltipRect.height) + 'px';
    }
    
    if (tooltipRect.left < 0) {
        tooltip.style.left = '10px';
    }
    
    if (tooltipRect.top < 0) {
        tooltip.style.top = '10px';
    }
}

// ============================================
// 步骤13：全景片结构化报告生成
// ============================================

/**
 * 构建全景片结构化报告
 * @param {Object} data - 全景片分析数据
 */
function buildPanoReport(data) {
    const container = document.getElementById('reportContent');
    if (!container) {
        console.error('报告内容容器不存在');
        return;
    }
    
    container.innerHTML = ''; // 清空
    
    // 1. 整体诊断摘要
    const summarySection = createReportSection('整体诊断摘要');
    
    // 汇总关键发现
    let summaryItems = [];
    
    // 颌骨对称性
    if (data.JointAndMandible && data.JointAndMandible.RamusSymmetry) {
        const symmetry = data.JointAndMandible.RamusSymmetry;
        if (symmetry.Status) {
            summaryItems.push(`颌骨对称性: ${symmetry.Status}`);
        }
    }
    
    // 牙周状况
    if (data.PeriodontalCondition) {
        const condition = data.PeriodontalCondition;
        if (condition.OverallStatus) {
            summaryItems.push(`牙周状况: ${condition.OverallStatus}`);
        }
    }
    
    // 智齿问题
    if (data.ThirdMolarSummary) {
        const wisdom = data.ThirdMolarSummary;
        if (wisdom.TotalCount !== undefined) {
            summaryItems.push(`智齿数量: ${wisdom.TotalCount}颗`);
        }
        if (wisdom.ImpactedCount !== undefined && wisdom.ImpactedCount > 0) {
            summaryItems.push(`阻生智齿: ${wisdom.ImpactedCount}颗`);
        }
    }
    
    // 缺牙情况
    if (data.MissingTeeth && Array.isArray(data.MissingTeeth) && data.MissingTeeth.length > 0) {
        summaryItems.push(`缺牙数量: ${data.MissingTeeth.length}颗`);
    }
    
    // 种植体
    if (data.ImplantAnalysis && data.ImplantAnalysis.Items && data.ImplantAnalysis.Items.length > 0) {
        summaryItems.push(`检测到种植体: ${data.ImplantAnalysis.Items.length}个`);
    }
    
    // 根尖密度影
    if (data.RootTipDensityAnalysis && data.RootTipDensityAnalysis.Items && data.RootTipDensityAnalysis.Items.length > 0) {
        summaryItems.push(`根尖密度影: ${data.RootTipDensityAnalysis.Items.length}处`);
    }
    
    // 上颌窦异常（炎症或III型过度气化）
    if (data.MaxillarySinus && Array.isArray(data.MaxillarySinus)) {
        const sinusAbnormal = data.MaxillarySinus.filter(s => s.Inflammation === true || s.Pneumatization === 3);
        if (sinusAbnormal.length > 0) {
            const abnormalSides = sinusAbnormal.map(s => s.Side === 'left' ? '右' : '左').join('、');
            summaryItems.push(`上颌窦异常: ${abnormalSides}侧`);
        }
    }
    
    if (summaryItems.length > 0) {
        summaryItems.forEach(item => {
            summarySection.appendChild(createKeyValue('', item));
        });
    } else {
        summarySection.appendChild(createKeyValue('', '暂无关键发现'));
    }
    
    container.appendChild(summarySection);
    
    // 2. 颌骨与关节
    const jointSection = createReportSection('颌骨与关节');
    let hasJointContent = false;
    
    if (data.JointAndMandible) {
        const joint = data.JointAndMandible;
        
        // 髁突评估
        if (joint.CondyleAssessment) {
            const condyle = joint.CondyleAssessment;
            
            // 左侧髁突（显示为右侧）
            if (condyle.condyle_Left) {
                const leftCondyle = condyle.condyle_Left;
                const morphologyText = leftCondyle.Morphology === 0 ? '正常' : '吸收';
                jointSection.appendChild(createKeyValue('右侧髁突形态', morphologyText));
                if (leftCondyle.Detail) {
                    jointSection.appendChild(createKeyValue('', leftCondyle.Detail));
                }
                if (leftCondyle.Confidence !== undefined) {
                    jointSection.appendChild(createKeyValue('置信度', (leftCondyle.Confidence * 100).toFixed(1) + '%'));
                }
                hasJointContent = true;
            }
            
            // 右侧髁突（显示为左侧）
            if (condyle.condyle_Right) {
                const rightCondyle = condyle.condyle_Right;
                const morphologyText = rightCondyle.Morphology === 0 ? '正常' : '吸收';
                jointSection.appendChild(createKeyValue('左侧髁突形态', morphologyText));
                if (rightCondyle.Detail) {
                    jointSection.appendChild(createKeyValue('', rightCondyle.Detail));
                }
                if (rightCondyle.Confidence !== undefined) {
                    jointSection.appendChild(createKeyValue('置信度', (rightCondyle.Confidence * 100).toFixed(1) + '%'));
                }
                hasJointContent = true;
            }
            
            // 髁突对称性
            if (condyle.OverallSymmetry !== undefined) {
                let symmetryText = '';
                if (condyle.OverallSymmetry === 0) {
                    symmetryText = '对称';
                } else if (condyle.OverallSymmetry === 1) {
                    symmetryText = '左侧大';
                } else if (condyle.OverallSymmetry === 2) {
                    symmetryText = '右侧大';
                }
                jointSection.appendChild(createKeyValue('髁突对称性', symmetryText));
                if (condyle.Confidence_Overall !== undefined) {
                    jointSection.appendChild(createKeyValue('置信度', (condyle.Confidence_Overall * 100).toFixed(1) + '%'));
                }
                hasJointContent = true;
            }
        }
        
        // 下颌支对称性
        if (joint.RamusSymmetry !== undefined) {
            const ramusText = joint.RamusSymmetry ? '对称' : '不对称';
            jointSection.appendChild(createKeyValue('下颌升支对称性', ramusText));
            hasJointContent = true;
        }
        
        // 下颌角对称性
        if (joint.GonialAngleSymmetry !== undefined) {
            const gonialText = joint.GonialAngleSymmetry ? '对称' : '不对称';
            jointSection.appendChild(createKeyValue('下颌角对称性', gonialText));
            hasJointContent = true;
        }
        
        // 总体描述
        if (joint.Detail) {
            jointSection.appendChild(createKeyValue('诊断描述', joint.Detail));
            hasJointContent = true;
        }
        
        // 总体置信度
        if (joint.Confidence !== undefined) {
            jointSection.appendChild(createKeyValue('置信度', (joint.Confidence * 100).toFixed(1) + '%'));
            hasJointContent = true;
        }
    }
    
    if (hasJointContent) {
        container.appendChild(jointSection);
    }
    
    // 2.5 上颌窦分析（独立专区）
    if (data.MaxillarySinus && Array.isArray(data.MaxillarySinus) && data.MaxillarySinus.length > 0) {
        const sinusSection = createReportSection('上颌窦分析');
        
        data.MaxillarySinus.forEach(sinus => {
            // 注意：图像左右与实际左右相反，所以left显示为"右"
            const sideName = sinus.Side === 'left' ? '右' : '左';
            
            // 创建单侧上颌窦卡片
            const sinusCard = document.createElement('div');
            sinusCard.className = 'sinus-card';
            
            // 判断是否有异常（炎症或III型过度气化）
            const hasAbnormal = sinus.Inflammation === true || sinus.Pneumatization === 3;
            if (hasAbnormal) {
                sinusCard.classList.add('abnormal');
            }
            
            // 标题
            const cardHeader = document.createElement('div');
            cardHeader.className = 'sinus-card-header';
            cardHeader.innerHTML = `<strong>${sideName}上颌窦</strong>`;
            sinusCard.appendChild(cardHeader);
            
            // 气化程度（按医学分型标准）
            // Ⅰ型: 正常/未气化 (距离>3mm)
            // Ⅱ型: 显著气化 (0-3mm)
            // Ⅲ型: 过度气化 (距离<0mm，牙根进入窦内)
            let pneumatizationText = 'Ⅰ型（正常）';
            let pneumatizationClass = 'normal';
            if (sinus.Pneumatization === 2) {
                pneumatizationText = 'Ⅱ型（显著气化）';
                pneumatizationClass = 'mild';
            } else if (sinus.Pneumatization === 3) {
                pneumatizationText = 'Ⅲ型（过度气化）';
                pneumatizationClass = 'severe';
            }
            
            const pneumatizationItem = document.createElement('div');
            pneumatizationItem.className = 'sinus-item';
            pneumatizationItem.innerHTML = `<span class="label">气化程度:</span> <span class="value ${pneumatizationClass}">${pneumatizationText}</span>`;
            sinusCard.appendChild(pneumatizationItem);
            
            // 炎症状态（重要指标）
            const inflammationItem = document.createElement('div');
            inflammationItem.className = 'sinus-item';
            const inflammationText = sinus.Inflammation ? '有炎症' : '无炎症';
            const inflammationClass = sinus.Inflammation ? 'inflammation-positive' : 'inflammation-negative';
            inflammationItem.innerHTML = `<span class="label">炎症状态:</span> <span class="value ${inflammationClass}">${inflammationText}</span>`;
            sinusCard.appendChild(inflammationItem);
            
            // 分类（如果有）
            if (sinus.TypeClassification !== undefined && sinus.TypeClassification !== 0) {
                const classItem = document.createElement('div');
                classItem.className = 'sinus-item';
                classItem.innerHTML = `<span class="label">分类:</span> <span class="value">Type ${sinus.TypeClassification}</span>`;
                sinusCard.appendChild(classItem);
            }
            
            // 牙根进入上颌窦（如果有）
            if (sinus.RootEntryToothFDI && Array.isArray(sinus.RootEntryToothFDI) && sinus.RootEntryToothFDI.length > 0) {
                const rootEntryItem = document.createElement('div');
                rootEntryItem.className = 'sinus-item root-entry';
                rootEntryItem.innerHTML = `<span class="label">牙根进入:</span> <span class="value">${sinus.RootEntryToothFDI.join(', ')} 牙位</span>`;
                sinusCard.appendChild(rootEntryItem);
            }
            
            // 详细描述
            if (sinus.Detail) {
                const detailItem = document.createElement('div');
                detailItem.className = 'sinus-detail';
                detailItem.textContent = sinus.Detail;
                sinusCard.appendChild(detailItem);
            }
            
            // 置信度
            const confidenceItem = document.createElement('div');
            confidenceItem.className = 'sinus-confidence';
            let confidenceText = '';
            if (sinus.Confidence_Inflammation !== undefined) {
                confidenceText += `炎症检测: ${(sinus.Confidence_Inflammation * 100).toFixed(1)}%`;
            }
            if (sinus.Confidence_Pneumatization !== undefined) {
                if (confidenceText) confidenceText += ' | ';
                confidenceText += `气化分析: ${(sinus.Confidence_Pneumatization * 100).toFixed(1)}%`;
            }
            if (confidenceText) {
                confidenceItem.innerHTML = `<span class="label">置信度:</span> ${confidenceText}`;
                sinusCard.appendChild(confidenceItem);
            }
            
            sinusSection.appendChild(sinusCard);
        });
        
        container.appendChild(sinusSection);
    }
    
    // 3. 牙周与缺牙
    const periodontalSection = createReportSection('牙周与缺牙');
    let hasPeriodontalContent = false;
    
    // 牙周状况
    if (data.PeriodontalCondition) {
        const condition = data.PeriodontalCondition;
        if (condition.OverallStatus) {
            periodontalSection.appendChild(createKeyValue('整体牙周状况', condition.OverallStatus));
            hasPeriodontalContent = true;
        }
        if (condition.AffectedTeeth && Array.isArray(condition.AffectedTeeth) && condition.AffectedTeeth.length > 0) {
            periodontalSection.appendChild(createKeyValue('受影响牙齿', condition.AffectedTeeth.join(', ')));
            hasPeriodontalContent = true;
        }
    }
    
    // 缺牙列表
    if (data.MissingTeeth && Array.isArray(data.MissingTeeth) && data.MissingTeeth.length > 0) {
        // 处理缺牙数据：可能是字符串数组或对象数组
        const missingTeethList = data.MissingTeeth.map(tooth => {
            if (typeof tooth === 'string') {
                return tooth + '牙位缺失';
            } else if (typeof tooth === 'object' && tooth.FDI) {
                return tooth.FDI + '牙位缺失';
            } else if (typeof tooth === 'object' && tooth.ToothNumber) {
                return tooth.ToothNumber + '牙位缺失';
            } else {
                return '缺失牙位';
            }
        });
        periodontalSection.appendChild(createKeyValue('缺牙列表', missingTeethList.join(', ')));
        hasPeriodontalContent = true;
    }
    
    if (hasPeriodontalContent) {
        container.appendChild(periodontalSection);
    }
    
    // 4. 智齿分析
    if (data.ThirdMolarSummary) {
        const wisdomSection = createReportSection('智齿分析');
        const wisdom = data.ThirdMolarSummary;
        
        if (wisdom.TotalCount !== undefined) {
            wisdomSection.appendChild(createKeyValue('智齿总数', wisdom.TotalCount + '颗'));
        }
        if (wisdom.ImpactedCount !== undefined) {
            wisdomSection.appendChild(createKeyValue('阻生智齿', wisdom.ImpactedCount + '颗'));
        }
        if (wisdom.EruptedCount !== undefined) {
            wisdomSection.appendChild(createKeyValue('已萌出', wisdom.EruptedCount + '颗'));
        }
        
        // 显示具体智齿情况
        if (data.ToothAnalysis && Array.isArray(data.ToothAnalysis)) {
            const wisdomTeeth = data.ToothAnalysis.filter(t => {
                const fdi = t.FDI || '';
                return fdi === '18' || fdi === '28' || fdi === '38' || fdi === '48';
            });
            
            if (wisdomTeeth.length > 0) {
                wisdomTeeth.forEach(tooth => {
                    const toothCard = createToothCard(tooth);
                    wisdomSection.appendChild(toothCard);
                });
            }
        }
        
        if (wisdomSection.querySelectorAll('.key-value-item, .tooth-card').length > 0) {
            container.appendChild(wisdomSection);
        }
    }
    
    // 5. 特殊发现
    const specialSection = createReportSection('特殊发现');
    let hasSpecialContent = false;
    
    // 种植体分析
    if (data.ImplantAnalysis && data.ImplantAnalysis.Items && Array.isArray(data.ImplantAnalysis.Items) && data.ImplantAnalysis.Items.length > 0) {
        const implantDiv = document.createElement('div');
        implantDiv.className = 'finding-group';
        implantDiv.innerHTML = '<h3>种植体</h3>';
        
        data.ImplantAnalysis.Items.forEach((implant, index) => {
            const item = document.createElement('div');
            item.className = 'finding-item';
            let content = `种植体 ${index + 1}: `;
            if (implant.Detail) {
                content += implant.Detail;
            }
            if (implant.Confidence !== undefined) {
                content += ` (置信度: ${(implant.Confidence * 100).toFixed(1)}%)`;
            }
            item.textContent = content;
            implantDiv.appendChild(item);
        });
        
        specialSection.appendChild(implantDiv);
        hasSpecialContent = true;
    }
    
    // 根尖密度影分析
    if (data.RootTipDensityAnalysis && data.RootTipDensityAnalysis.Items && Array.isArray(data.RootTipDensityAnalysis.Items) && data.RootTipDensityAnalysis.Items.length > 0) {
        const densityDiv = document.createElement('div');
        densityDiv.className = 'finding-group';
        densityDiv.innerHTML = '<h3>根尖密度影</h3>';
        
        data.RootTipDensityAnalysis.Items.forEach((density, index) => {
            const item = document.createElement('div');
            item.className = 'finding-item';
            let content = `密度影 ${index + 1}: `;
            if (density.Detail) {
                content += density.Detail;
            }
            if (density.Confidence !== undefined) {
                content += ` (置信度: ${(density.Confidence * 100).toFixed(1)}%)`;
            }
            item.textContent = content;
            densityDiv.appendChild(item);
        });
        
        specialSection.appendChild(densityDiv);
        hasSpecialContent = true;
    }
    
    if (hasSpecialContent) {
        container.appendChild(specialSection);
    }
    
    // 6. 单牙诊断详情
    if (data.ToothAnalysis && Array.isArray(data.ToothAnalysis) && data.ToothAnalysis.length > 0) {
        const toothDetailSection = createReportSection('单牙诊断详情');
        
        // 过滤掉智齿（已在智齿分析中显示）
        const nonWisdomTeeth = data.ToothAnalysis.filter(t => {
            const fdi = t.FDI || '';
            return fdi !== '18' && fdi !== '28' && fdi !== '38' && fdi !== '48';
        });
        
        if (nonWisdomTeeth.length > 0) {
            nonWisdomTeeth.forEach(tooth => {
                const toothCard = createToothCard(tooth);
                toothDetailSection.appendChild(toothCard);
            });
            container.appendChild(toothDetailSection);
        }
    }
    
    // 7. JSON 数据输出（可展开/折叠）
    const jsonSection = createReportSection('完整数据 (JSON)');
    const jsonToggle = document.createElement('button');
    jsonToggle.className = 'json-toggle-btn';
    jsonToggle.textContent = '展开 JSON 数据';
    jsonToggle.onclick = function() {
        const jsonContent = jsonSection.querySelector('.json-content');
        if (jsonContent) {
            if (jsonContent.style.display === 'none') {
                jsonContent.style.display = 'block';
                jsonToggle.textContent = '折叠 JSON 数据';
            } else {
                jsonContent.style.display = 'none';
                jsonToggle.textContent = '展开 JSON 数据';
            }
        }
    };
    jsonSection.appendChild(jsonToggle);
    
    const jsonContent = document.createElement('pre');
    jsonContent.className = 'json-content';
    jsonContent.style.display = 'none';
    jsonContent.style.whiteSpace = 'pre-wrap';
    jsonContent.style.wordWrap = 'break-word';
    jsonContent.style.fontSize = '11px';
    jsonContent.style.backgroundColor = '#f5f5f5';
    jsonContent.style.padding = '10px';
    jsonContent.style.borderRadius = '4px';
    jsonContent.style.overflowX = 'auto';
    jsonContent.textContent = JSON.stringify(data, null, 2);
    jsonSection.appendChild(jsonContent);
    
    container.appendChild(jsonSection);
}

/**
 * 创建单牙诊断卡片
 * @param {Object} tooth - 牙齿数据
 * @returns {HTMLElement} 牙齿卡片元素
 */
function createToothCard(tooth) {
    const card = document.createElement('div');
    card.className = 'tooth-card';
    
    // 判断是否有异常发现
    const hasAbnormal = tooth.Properties && Array.isArray(tooth.Properties) && 
                       tooth.Properties.some(p => {
                           // 根据属性类型判断是否为异常
                           const value = p.Value || '';
                           return value.includes('carious') || 
                                  value.includes('absorption') || 
                                  value.includes('fracture') ||
                                  value.includes('resorption');
                       });
    
    if (hasAbnormal) {
        card.classList.add('abnormal');
    }
    
    // 构建卡片内容
    let content = `<div class="tooth-header">牙位: ${tooth.FDI || 'N/A'}</div>`;
    
    // 显示属性类发现
    if (tooth.Properties && Array.isArray(tooth.Properties) && tooth.Properties.length > 0) {
        content += '<div class="tooth-properties">';
        tooth.Properties.forEach(prop => {
            const description = prop.Description || prop.Value || '未知';
            const confidence = prop.Confidence !== undefined ? (prop.Confidence * 100).toFixed(1) : 'N/A';
            content += `<div class="tooth-property-item">${description} (${confidence}%)</div>`;
        });
        content += '</div>';
    } else {
        content += '<div class="tooth-properties">未发现异常</div>';
    }
    
    // 显示牙周吸收等级
    if (tooth.PeriodontalLevel !== undefined) {
        const levelText = formatPeriodontalLevel(tooth.PeriodontalLevel);
        content += `<div class="tooth-periodontal">牙周吸收等级: ${levelText}</div>`;
    }
    
    // 显示智齿等级
    if (tooth.WisdomLevel !== undefined) {
        const levelText = formatWisdomLevel(tooth.WisdomLevel);
        content += `<div class="tooth-wisdom">智齿等级: ${levelText}</div>`;
    }
    
    card.innerHTML = content;
    return card;
}

/**
 * 格式化牙周吸收等级
 * @param {number} level - 等级 (0/1/2/3)
 * @returns {string} 等级文本
 */
function formatPeriodontalLevel(level) {
    const levels = {
        0: '正常',
        1: '轻度吸收',
        2: '中度吸收',
        3: '重度吸收'
    };
    return levels[level] || `等级 ${level}`;
}

/**
 * 格式化智齿等级
 * @param {number} level - 等级 (1-4)
 * @returns {string} 等级文本
 */
function formatWisdomLevel(level) {
    const levels = {
        1: '完全萌出',
        2: '部分萌出',
        3: '阻生',
        4: '未萌出'
    };
    return levels[level] || `等级 ${level}`;
}

// ============================================
// 步骤14：完善错误处理和边界情况
// ============================================

/**
 * 完善的 resetUI 函数
 * 功能：
 * 1. 清空 Konva Stage 和所有图层
 * 2. 销毁 Stage 实例
 * 3. 清空报告容器
 * 4. 隐藏所有结果区域
 * 5. 清空错误提示
 * 6. 重置全局状态
 */
function resetUI() {
    console.log('重置 UI');
    
    // 1. 清空 Canvas 和 Konva 对象
    clearCanvas();
    
    // 2. 清空报告容器
    clearReport();
    
    // 3. 隐藏主容器
    const mainContainer = document.getElementById('mainContainer');
    if (mainContainer) {
        mainContainer.classList.add('hidden');
    }
    
    // 4. 隐藏错误提示
    const errorMessage = document.getElementById('errorMessage');
    if (errorMessage) {
        errorMessage.classList.add('hidden');
        errorMessage.textContent = '';
    }
    
    // 5. 隐藏加载指示器
    hideLoading();
    
    // 6. 重置全局状态
    appState.currentTaskId = null;
    appState.currentTaskType = null;
    appState.cachedResult = null;
    appState.imageScale = 1.0;
    appState.originalImage = null;
    
    // 7. 重新启用提交按钮
    const submitBtn = document.getElementById('submitBtn');
    if (submitBtn) {
        submitBtn.disabled = false;
    }
    
    console.log('UI 重置完成');
}

/**
 * 处理图片加载失败的情况
 * 在 renderCephalometric 和 renderPanoramic 中已经实现了 img.onerror 回调
 * 这里提供一个通用的错误处理函数
 */
function handleImageLoadError(errorMsg) {
    console.error('图片加载错误:', errorMsg);
    displayError({ displayMessage: errorMsg || '图片加载失败，请检查文件格式' });
}

/**
 * 安全地访问嵌套对象属性
 * 使用可选链操作符的兼容性方案
 * @param {Object} obj - 对象
 * @param {string} path - 属性路径，如 'a.b.c'
 * @param {*} defaultValue - 默认值
 * @returns {*} 属性值或默认值
 */
function safeGet(obj, path, defaultValue = undefined) {
    if (!obj || typeof path !== 'string') {
        return defaultValue;
    }
    
    const keys = path.split('.');
    let current = obj;
    
    for (let key of keys) {
        if (current === null || current === undefined) {
            return defaultValue;
        }
        current = current[key];
    }
    
    return current !== undefined ? current : defaultValue;
}

/**
 * 验证坐标数据的有效性
 * @param {number} x - X 坐标
 * @param {number} y - Y 坐标
 * @returns {boolean} 坐标是否有效
 */
function isValidCoordinate(x, y) {
    return typeof x === 'number' && typeof y === 'number' && 
           !isNaN(x) && !isNaN(y) && 
           isFinite(x) && isFinite(y);
}

/**
 * 验证数组坐标的有效性
 * @param {Array} coords - 坐标数组
 * @returns {boolean} 坐标数组是否有效
 */
function isValidCoordinateArray(coords) {
    if (!Array.isArray(coords) || coords.length === 0) {
        return false;
    }
    
    // 检查是否为 [[x,y], [x,y], ...] 格式
    if (Array.isArray(coords[0])) {
        return coords.every(point => 
            Array.isArray(point) && 
            point.length >= 2 && 
            isValidCoordinate(point[0], point[1])
        );
    }
    
    // 检查是否为 [x1, y1, x2, y2, ...] 格式
    if (coords.length % 2 === 0) {
        for (let i = 0; i < coords.length; i += 2) {
            if (!isValidCoordinate(coords[i], coords[i + 1])) {
                return false;
            }
        }
        return true;
    }
    
    return false;
}

/**
 * 处理响应式缩放
 * 当容器尺寸变化时，重新计算坐标
 * @param {number} originalX - 原始 X 坐标
 * @param {number} originalY - 原始 Y 坐标
 * @param {number} oldScale - 旧缩放比例
 * @param {number} newScale - 新缩放比例
 * @returns {{x: number, y: number}} 重新计算后的坐标
 */
function recalculateCoordinatesOnResize(originalX, originalY, oldScale, newScale) {
    // 先反缩放回原始坐标
    const unscaledX = originalX / oldScale;
    const unscaledY = originalY / oldScale;
    
    // 再应用新的缩放比例
    return {
        x: unscaledX * newScale,
        y: unscaledY * newScale
    };
}

/**
 * 处理 JSON 数据结构不完整的情况
 * 在访问嵌套属性前检查对象是否存在
 * 示例：
 *   const landmarks = data?.LandmarkPositions?.Landmarks || [];
 *   const toothAnalysis = data?.ToothAnalysis || [];
 */

/**
 * 增强的 displayResult 函数，包含更多错误检查
 * 这是对现有 displayResult 的补充说明
 * 实际的 displayResult 已在步骤6中实现，这里补充额外的错误处理
 */
function validateResultData(resultJson) {
    // 检查结果对象是否存在
    if (!resultJson || typeof resultJson !== 'object') {
        return { valid: false, error: '结果数据格式无效' };
    }
    
    // 检查状态字段
    if (!resultJson.status) {
        return { valid: false, error: '结果缺少 status 字段' };
    }
    
    // 如果是成功状态，检查数据字段
    if (resultJson.status === 'SUCCESS') {
        if (!resultJson.data || typeof resultJson.data !== 'object') {
            return { valid: false, error: '成功结果缺少有效的 data 字段' };
        }
    }
    
    // 如果是失败状态，检查错误字段
    if (resultJson.status === 'FAILURE') {
        if (!resultJson.error || typeof resultJson.error !== 'object') {
            return { valid: false, error: '失败结果缺少有效的 error 字段' };
        }
    }
    
    return { valid: true };
}

/**
 * 处理窗口大小变化时的响应式表现
 * 添加窗口 resize 事件监听
 */
/**
 * 处理窗口大小变化时的响应式表现
 * 修复版：先销毁旧画布，让容器回缩，再测量渲染
 */
function setupWindowResizeHandler() {
    let resizeTimer = null;
    
    window.addEventListener('resize', function() {
        if (resizeTimer) {
            clearTimeout(resizeTimer);
        }
        
        resizeTimer = setTimeout(function() {
            const hasData = appState.cachedResult && appState.cachedResult.data;
            const hasImage = appState.originalImage;
            const taskType = appState.currentTaskType;

            if (hasData && hasImage && taskType) {
                console.log('窗口大小改变，准备重绘...');
                
                //先销毁当前的 Stage 并清空容器
                // 这样 div 就会失去支撑，回缩到 CSS 布局定义的正确大小
                if (appState.konvaStage) {
                    appState.konvaStage.destroy();
                    appState.konvaStage = null;
                }
                
                const container = document.getElementById('imageContainer');
                if (container) {
                    container.innerHTML = ''; // 确保彻底清空
                }


                // 2. 此时 container.clientWidth 已经是正确的回缩后的大小了
                if (container && container.clientWidth > 0 && container.clientHeight > 0) {
                    if (taskType === 'cephalometric') {
                        renderCephalometric(appState.cachedResult.data);
                    } else if (taskType === 'panoramic') {
                        renderPanoramic(appState.cachedResult.data);
                    }
                }
            }
        }, 200); // 防抖时间
    });
}

/**
 * 初始化时调用 setupWindowResizeHandler
 * 在 init() 函数中添加以下代码：
 * setupWindowResizeHandler();
 */

// ============================================
// 步骤15：优化样式和用户体验
// ============================================

/**
 * 增强的 Tooltip 样式和交互
 * 添加箭头指向和更好的视觉效果
 */
function createEnhancedTooltip(content, position = { x: 0, y: 0 }) {
    const tooltip = document.createElement('div');
    tooltip.className = 'tooltip enhanced-tooltip';
    tooltip.innerHTML = content;
    
    // 设置位置
    tooltip.style.left = position.x + 'px';
    tooltip.style.top = position.y + 'px';
    
    // 添加到页面
    document.body.appendChild(tooltip);
    
    // 调整位置，确保不超出视口
    const tooltipRect = tooltip.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const padding = 10;
    
    let adjustedX = position.x;
    let adjustedY = position.y;
    
    if (tooltipRect.right > viewportWidth - padding) {
        adjustedX = viewportWidth - tooltipRect.width - padding;
    }
    
    if (tooltipRect.bottom > viewportHeight - padding) {
        adjustedY = viewportHeight - tooltipRect.height - padding;
    }
    
    if (tooltipRect.left < padding) {
        adjustedX = padding;
    }
    
    if (tooltipRect.top < padding) {
        adjustedY = padding;
    }
    
    tooltip.style.left = adjustedX + 'px';
    tooltip.style.top = adjustedY + 'px';
    
    return tooltip;
}

/**
 * 添加加载状态样式
 * 在图像加载时显示占位符
 */
function showImageLoadingPlaceholder() {
    const container = document.getElementById('imageContainer');
    if (!container) return;
    
    // 清空容器
    container.innerHTML = '';
    
    // 创建占位符
    const placeholder = document.createElement('div');
    placeholder.className = 'image-loading-placeholder';
    placeholder.innerHTML = `
        <div class="placeholder-spinner"></div>
        <p class="placeholder-text">正在加载图像...</p>
    `;
    
    container.appendChild(placeholder);
}

/**
 * 移除加载状态占位符
 */
function removeImageLoadingPlaceholder() {
    const placeholder = document.querySelector('.image-loading-placeholder');
    if (placeholder) {
        placeholder.remove();
    }
}

/**
 * 添加报告卡片的过渡动画
 * 在 buildCephReport 和 buildPanoReport 中调用
 */
function addReportSectionAnimations() {
    const sections = document.querySelectorAll('.report-section');
    sections.forEach((section, index) => {
        // 添加淡入动画
        section.style.opacity = '0';
        section.style.transform = 'translateY(10px)';
        section.style.transition = `opacity 0.3s ease ${index * 50}ms, transform 0.3s ease ${index * 50}ms`;
        
        // 触发动画
        setTimeout(() => {
            section.style.opacity = '1';
            section.style.transform = 'translateY(0)';
        }, 10);
    });
}

/**
 * 优化报告区域的滚动体验
 * 添加平滑滚动
 */
function enableSmoothScrolling() {
    const reportContainer = document.getElementById('reportContainer');
    if (reportContainer) {
        reportContainer.style.scrollBehavior = 'smooth';
    }
}

/**
 * 添加键盘快捷键支持
 * ESC 键：关闭 Tooltip
 * R 键：重置 UI
 */
function setupKeyboardShortcuts() {
    document.addEventListener('keydown', function(event) {
        // ESC 键：隐藏 Tooltip
        if (event.key === 'Escape') {
            hideTooltip();
        }
        
        // R 键（Ctrl+R 除外）：重置 UI
        if (event.key === 'r' && !event.ctrlKey && !event.metaKey) {
            // 可选：重置 UI
            // resetUI();
        }
    });
}

/**
 * 增强的错误提示样式
 * 添加自动关闭功能
 */
function displayErrorWithAutoClose(error, autoCloseTime = 5000) {
    displayError(error);
    
    // 自动关闭错误提示
    if (autoCloseTime > 0) {
        setTimeout(() => {
            const errorMessage = document.getElementById('errorMessage');
            if (errorMessage) {
                errorMessage.classList.add('hidden');
            }
        }, autoCloseTime);
    }
}

/**
 * 添加报告卡片的悬停效果
 */
function addReportCardHoverEffects() {
    const cards = document.querySelectorAll('.measurement-item, .tooth-card');
    cards.forEach(card => {
        card.addEventListener('mouseenter', function() {
            this.style.transform = 'translateX(4px)';
            this.style.boxShadow = '0 2px 8px rgba(0,0,0,0.1)';
        });
        
        card.addEventListener('mouseleave', function() {
            this.style.transform = 'translateX(0)';
            this.style.boxShadow = 'none';
        });
    });
}

/**
 * 在 init() 函数中调用以下函数来启用步骤15的优化：
 * setupWindowResizeHandler();
 * setupKeyboardShortcuts();
 * enableSmoothScrolling();
 */

// ============================================
// 步骤16：图层显示/隐藏控制功能
// ============================================

/**
 * 图层配置映射表
 * 定义每个图层的显示名称和对应的图层key
 */
const LAYER_CONFIG = {
    // 侧位片图层
    landmarks: { name: '关键点', taskType: 'cephalometric' },
    cvm: { name: '颈椎成熟度', taskType: 'cephalometric' },
    measurementLines: { name: '测量线', taskType: 'cephalometric' },
    // 全景片图层
    toothSegments: { name: '牙齿分割', taskType: 'panoramic' },
    implants: { name: '种植体', taskType: 'panoramic' },
    condyle: { name: '髁突', taskType: 'panoramic' },
    mandible: { name: '下颌升支', taskType: 'panoramic' },
    sinus: { name: '上颌窦', taskType: 'panoramic' },
    density: { name: '根尖密度影', taskType: 'panoramic' }
};

/**
 * 初始化图层控制面板
 * 根据当前任务类型动态生成图层列表
 */
function initLayerControlPanel() {
    console.log('初始化图层控制面板...');
    const panel = document.getElementById('layerControlPanel');
    const layerList = document.getElementById('layerList');
    
    if (!panel) {
        console.error('图层控制面板元素不存在: layerControlPanel');
        return;
    }
    
    if (!layerList) {
        console.error('图层列表元素不存在: layerList');
        return;
    }
    
    console.log('找到图层控制面板元素');
    
    // 清空现有列表
    layerList.innerHTML = '';
    
    // 根据任务类型显示对应的图层
    const taskType = appState.currentTaskType;
    if (!taskType) {
        console.warn('任务类型未设置，隐藏面板');
        panel.style.display = 'none';
        return;
    }
    
    console.log('任务类型:', taskType, '已创建的图层:', Object.keys(appState.konvaLayers));
    
    // 生成图层列表项（只显示实际存在的图层）
    let hasLayers = false;
    Object.keys(LAYER_CONFIG).forEach(layerKey => {
        const config = LAYER_CONFIG[layerKey];
        
        // 只显示当前任务类型对应的图层，且该图层必须存在
        if (config.taskType === taskType && appState.konvaLayers[layerKey]) {
            console.log('添加图层项:', layerKey, config.name);
            const layerItem = createLayerItem(layerKey, config.name);
            layerList.appendChild(layerItem);
            hasLayers = true;
            
            // 初始化显示状态为true
            if (appState.layerVisibility[layerKey] === undefined) {
                appState.layerVisibility[layerKey] = true;
            }
        }
    });
    
    // 如果没有任何图层，隐藏面板
    if (!hasLayers) {
        console.warn('没有找到可用的图层，隐藏面板');
        panel.style.display = 'none';
        return;
    }
    
    // 显示面板 - 使用多种方式确保显示
    panel.style.display = 'block';
    panel.style.visibility = 'visible';
    panel.style.opacity = '1';
    panel.style.pointerEvents = 'auto';
    
    // 确保面板在最上层
    panel.style.zIndex = '10000';
    
    console.log('图层控制面板已显示，包含', layerList.children.length, '个图层项');
    console.log('面板位置:', panel.getBoundingClientRect());
    
    // 绑定全部隐藏/显示按钮事件
    const hideAllBtn = document.getElementById('hideAllBtn');
    const showAllBtn = document.getElementById('showAllBtn');
    
    if (hideAllBtn) {
        hideAllBtn.onclick = hideAllLayers;
        console.log('已绑定全部隐藏按钮');
    } else {
        console.warn('未找到全部隐藏按钮: hideAllBtn');
    }
    
    if (showAllBtn) {
        showAllBtn.onclick = showAllLayers;
        console.log('已绑定全部显示按钮');
    } else {
        console.warn('未找到全部显示按钮: showAllBtn');
    }
    
    const showAllMeasurementsBtn = document.getElementById('showAllMeasurementsBtn');
    if (showAllMeasurementsBtn) {
        showAllMeasurementsBtn.onclick = renderAllMeasurements;
        console.log('已绑定显示所有测量线按钮');
    } else {
        console.warn('未找到显示所有测量线按钮: showAllMeasurementsBtn');
    }
    
    // 更新所有图层的显示状态
    updateAllLayersVisibility();
    
    // 延迟再次检查，确保面板显示（处理可能的异步问题）
    setTimeout(() => {
        if (panel.style.display === 'none' || panel.style.display === '') {
            console.warn('面板被隐藏，强制显示');
            panel.style.display = 'block';
        }
        const rect = panel.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) {
            console.warn('面板尺寸为0，可能被遮挡');
        } else {
            console.log('面板最终位置和尺寸:', rect);
        }
    }, 100);
}

/**
 * 创建图层列表项
 * @param {string} layerKey - 图层key
 * @param {string} layerName - 图层显示名称
 * @returns {HTMLElement} 图层列表项元素
 */
function createLayerItem(layerKey, layerName) {
    const item = document.createElement('div');
    item.className = 'layer-item';
    
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.id = `layer-${layerKey}`;
    checkbox.checked = appState.layerVisibility[layerKey] !== false;
    
    const label = document.createElement('label');
    label.htmlFor = `layer-${layerKey}`;
    label.textContent = layerName;
    
    // 绑定事件：利用 checkbox 的 change 事件作为单一事实来源
    checkbox.onchange = function(e) {
        toggleLayerVisibility(layerKey, checkbox.checked);
    };

    // 容器点击事件：将点击代理到 checkbox
    item.onclick = function(e) {
        // 如果点击的是 label，浏览器会自动触发 checkbox 的点击，无需干预
        if (e.target === label) {
            return;
        }
        
        // 如果点击的是 checkbox 本身，无需干预（会自动触发 change）
        if (e.target === checkbox) {
            return;
        }

        // 点击容器其他区域，手动触发 checkbox 的点击
        // 这会触发 input change 事件，从而执行上面的逻辑
        checkbox.click();
    };
    
    item.appendChild(checkbox);
    item.appendChild(label);
    
    return item;
}

/**
 * 切换图层显示/隐藏
 * @param {string} layerKey - 图层key
 * @param {boolean} visible - 是否显示
 */
function toggleLayerVisibility(layerKey, visible) {
    appState.layerVisibility[layerKey] = visible;
    
    const layer = appState.konvaLayers[layerKey];
    if (layer) {
        layer.visible(visible);
        if (appState.konvaStage) {
            appState.konvaStage.draw();
        }
    }
    
    console.log(`图层 ${layerKey} ${visible ? '显示' : '隐藏'}`);
}

/**
 * 更新所有图层的显示状态
 * 根据 appState.layerVisibility 同步图层实际显示状态
 */
function updateAllLayersVisibility() {
    Object.keys(appState.layerVisibility).forEach(layerKey => {
        const visible = appState.layerVisibility[layerKey] !== false;
        const layer = appState.konvaLayers[layerKey];
        
        if (layer) {
            layer.visible(visible);
        }
    });
    
    // 更新checkbox状态
    Object.keys(appState.layerVisibility).forEach(layerKey => {
        const checkbox = document.getElementById(`layer-${layerKey}`);
        if (checkbox) {
            checkbox.checked = appState.layerVisibility[layerKey] !== false;
        }
    });
    
    if (appState.konvaStage) {
        appState.konvaStage.draw();
    }
}

/**
 * 全部隐藏所有图层
 */
function hideAllLayers() {
    Object.keys(LAYER_CONFIG).forEach(layerKey => {
        const config = LAYER_CONFIG[layerKey];
        if (config.taskType === appState.currentTaskType) {
            appState.layerVisibility[layerKey] = false;
        }
    });
    
    // 统一更新图层可见性和 Checkbox 状态，并触发一次重绘
    updateAllLayersVisibility();
    console.log('全部图层已隐藏');
}

/**
 * 全部显示所有图层
 */
function showAllLayers() {
    Object.keys(LAYER_CONFIG).forEach(layerKey => {
        const config = LAYER_CONFIG[layerKey];
        if (config.taskType === appState.currentTaskType) {
            appState.layerVisibility[layerKey] = true;
        }
    });
    
    // 统一更新图层可见性和 Checkbox 状态，并触发一次重绘
    updateAllLayersVisibility();
    console.log('全部图层已显示');
}

/**
 * 为可视化元素添加点击切换显示/隐藏功能
 * 点击元素时，切换其所在图层的显示状态
 * @param {Konva.Node} node - Konva节点
 * @param {string} layerKey - 图层key
 */
function addClickToggleToNode(node, layerKey) {
    if (!node || !layerKey) return;
    
    node.on('click', function(e) {
        e.cancelBubble = true; // 阻止事件冒泡
        
        // 切换图层显示状态
        const currentVisible = appState.layerVisibility[layerKey] !== false;
        const newVisible = !currentVisible;
        
        toggleLayerVisibility(layerKey, newVisible);
        
        // 更新对应的checkbox
        const checkbox = document.getElementById(`layer-${layerKey}`);
        if (checkbox) {
            checkbox.checked = newVisible;
        }
        
        console.log(`点击切换图层 ${layerKey}，新状态: ${newVisible ? '显示' : '隐藏'}`);
    });
}

