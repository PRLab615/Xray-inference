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
    pollingTimer: null,        // 轮询定时器
    pollingStartTime: null,    // 轮询开始时间
    cachedResult: null,        // 缓存的结果JSON
    viewMode: 'full'           // 视图模式: 'full' (完整) 或 'compact' (简洁)
};

// 全局配置常量
const CONFIG = {
    AI_BACKEND_URL: 'http://192.168.1.17:18000/api/v1/analyze',
    CALLBACK_URL: 'http://192.168.1.17:5000/callback',
    POLL_INTERVAL: 3000,       // 3秒
    POLL_TIMEOUT: 360000       // 6分钟
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
    
    // 绑定提交按钮（步骤5实现）
    document.getElementById('submitBtn').addEventListener('click', onSubmit);
    
    // 绑定复制按钮（步骤7实现）
    document.getElementById('copyBtn').addEventListener('click', onCopy);
    
    // 绑定视图切换按钮
    document.getElementById('viewToggleBtn').addEventListener('click', onViewToggle);
    
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
    
    // 检测是否是文件变化（重新选择文件）
    // 如果用户在任何状态下重新选择文件，触发重置（步骤8实现）
    // if (fileInput.files.length > 0) {
    //     if (appState.currentTaskId || appState.pollingTimer) {
    //         console.log('检测到文件变化，重置 UI');
    //         resetUI();
    //         return;
    //     }
    // }
    
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

// ============================================
// 步骤5：任务提交逻辑（不含轮询）
// ============================================

/**
 * 处理任务提交
 * 功能：
 * 1. 生成 UUID 作为 taskId
 * 2. 构建 FormData，包含 taskId, taskType, callbackUrl, image
 * 3. 如果需要患者信息，添加 patientInfo 字段（JSON 字符串）
 * 4. 发送 POST 请求到 AI 后端
 * 5. 处理响应：202 成功、4xx 错误、网络错误
 */
async function onSubmit() {
    const fileInput = document.getElementById('imageFile');
    const file = fileInput.files[0];
    
    // 校验：必须选择文件
    if (!file) {
        alert('请先选择文件');
        return;
    }
    
    // 生成 taskId (UUID v4) - 兼容不支持 crypto.randomUUID 的环境
    const taskId = generateUUID();
    console.log('生成任务ID:', taskId);
    
    // 构建 FormData
    const formData = new FormData();
    formData.append('taskId', taskId);
    formData.append('taskType', document.getElementById('taskType').value);
    formData.append('callbackUrl', CONFIG.CALLBACK_URL);
    formData.append('image', file);
    
    // 如果患者信息表单显示，添加 patientInfo 字段
    const patientInfoSection = document.getElementById('patientInfoSection');
    if (!patientInfoSection.classList.contains('hidden')) {
        const patientInfo = {
            gender: document.getElementById('gender').value,
            DentalAgeStage: document.getElementById('dentalStage').value
        };
        formData.append('patientInfo', JSON.stringify(patientInfo));
        console.log('患者信息:', patientInfo);
    }
    
    // 禁用提交按钮，防止重复提交
    const submitBtn = document.getElementById('submitBtn');
    submitBtn.disabled = true;
    
    try {
        console.log('发送请求到:', CONFIG.AI_BACKEND_URL);
        const response = await fetch(CONFIG.AI_BACKEND_URL, {
            method: 'POST',
            body: formData
        });
        
        if (response.status === 202) {
            // 提交成功 (202 Accepted)
            appState.currentTaskId = taskId;
            showLoading();
            console.log('任务提交成功，taskId:', taskId);
            
            // 启动轮询（步骤6实现）
            startPolling(taskId);
        } else {
            // 同步验证失败（4xx 错误）
            const errorData = await response.json();
            const errorMsg = errorData.error?.displayMessage || '提交失败';
            alert('错误：' + errorMsg);
            console.error('提交失败:', errorData);
            submitBtn.disabled = false;
        }
    } catch (error) {
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
// 步骤7：结果展示和复制功能
// ============================================

/**
 * 在页面上展示分析结果或错误信息
 * 功能：
 * 1. 隐藏加载图标
 * 2. 根据 status 字段判断成功或失败
 * 3. 成功时显示 data 字段（根据 viewMode 决定完整或简洁）
 * 4. 失败时显示 error.displayMessage
 * 5. 显示结果容器和复制按钮
 */
function displayResult(resultJson) {
    hideLoading();
    
    const resultContainer = document.getElementById('resultContainer');
    const resultJsonElement = document.getElementById('resultJson');
    
    // 根据状态显示不同内容
    if (resultJson.status === 'SUCCESS') {
        // 成功：根据视图模式显示 data 字段
        const dataToDisplay = appState.viewMode === 'compact' 
            ? simplifyJSON(resultJson.data) 
            : resultJson.data;
        
        const displayText = '状态：成功\n\n分析结果：\n' + 
                           JSON.stringify(dataToDisplay, null, 2);
        resultJsonElement.textContent = displayText;
        resultJsonElement.className = 'result-json result-success';
        console.log('结果展示：成功 (视图模式:', appState.viewMode + ')');
    } else if (resultJson.status === 'FAILURE') {
        // 失败：显示错误信息
        const errorMsg = resultJson.error?.displayMessage || '未知错误';
        const displayText = '状态：失败\n\n错误信息：\n' + errorMsg;
        resultJsonElement.textContent = displayText;
        resultJsonElement.className = 'result-json result-error';
        console.log('结果展示：失败 -', errorMsg);
    } else {
        // 其他状态（兜底）
        const dataToDisplay = appState.viewMode === 'compact' 
            ? simplifyJSON(resultJson) 
            : resultJson;
        resultJsonElement.textContent = JSON.stringify(dataToDisplay, null, 2);
        resultJsonElement.className = 'result-json';
        console.log('结果展示：其他状态 -', resultJson.status);
    }
    
    // 显示结果容器
    resultContainer.classList.remove('hidden');
    
    // 重新启用提交按钮（允许提交新任务）
    document.getElementById('submitBtn').disabled = false;
}

/**
 * 将完整的回调 JSON 复制到剪贴板
 * 功能：
 * 1. 读取 appState.cachedResult
 * 2. 序列化为 JSON 字符串
 * 3. 优先使用 navigator.clipboard API，失败时降级到传统方法
 * 4. 显示"已复制"提示
 */
async function onCopy() {
    if (!appState.cachedResult) {
        alert('没有可复制的内容');
        return;
    }
    
    const jsonString = JSON.stringify(appState.cachedResult, null, 2);
    
    // 尝试使用现代 Clipboard API
    if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
            await navigator.clipboard.writeText(jsonString);
            showCopySuccess();
            console.log('已复制到剪贴板 (使用 Clipboard API)');
            return;
        } catch (error) {
            console.warn('Clipboard API 失败，尝试降级方案:', error);
        }
    }
    
    // 降级方案：使用传统的 execCommand 方法
    const success = copyToClipboardFallback(jsonString);
    if (success) {
        showCopySuccess();
        console.log('已复制到剪贴板 (使用降级方案)');
    } else {
        alert('复制失败，请手动复制内容');
        console.error('所有复制方法均失败');
    }
}

/**
 * 显示复制成功的视觉反馈
 */
function showCopySuccess() {
    const copyBtn = document.getElementById('copyBtn');
    const originalText = copyBtn.textContent;
    copyBtn.textContent = '✓ 已复制';
    copyBtn.style.backgroundColor = '#27ae60';
    
    // 2秒后恢复按钮文本和样式
    setTimeout(() => {
        copyBtn.textContent = originalText;
        copyBtn.style.backgroundColor = '';
    }, 2000);
}

/**
 * 降级复制方案：使用 document.execCommand (兼容旧浏览器和 HTTP 环境)
 * @param {string} text - 要复制的文本
 * @returns {boolean} - 是否成功
 */
function copyToClipboardFallback(text) {
    // 创建临时 textarea 元素
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.top = '0';
    textarea.style.left = '0';
    textarea.style.width = '1px';
    textarea.style.height = '1px';
    textarea.style.padding = '0';
    textarea.style.border = 'none';
    textarea.style.outline = 'none';
    textarea.style.boxShadow = 'none';
    textarea.style.background = 'transparent';
    
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    
    let success = false;
    try {
        success = document.execCommand('copy');
    } catch (error) {
        console.error('execCommand 复制失败:', error);
    }
    
    document.body.removeChild(textarea);
    return success;
}

// ============================================
// 视图切换功能：简洁视图 vs 完整视图
// ============================================

/**
 * 简化JSON对象：折叠冗长字段（如坐标数组、序列化mask）
 * 处理规则：
 * 1. SegmentationMask.Coordinates: 超过3个坐标点时，只显示前2个+省略+最后1个
 * 2. SegmentationMask.SerializedMask: 超过20字符时截断显示前20字符
 * 3. 递归处理所有嵌套对象和数组
 */
function simplifyJSON(obj) {
    if (obj === null || obj === undefined) {
        return obj;
    }
    
    // 处理数组
    if (Array.isArray(obj)) {
        return obj.map(item => simplifyJSON(item));
    }
    
    // 处理对象
    if (typeof obj === 'object') {
        const simplified = {};
        
        for (const key in obj) {
            const value = obj[key];
            
            // 特殊处理：Coordinates 坐标数组
            if (key === 'Coordinates' && Array.isArray(value)) {
                if (value.length > 3) {
                    simplified[key] = [
                        value[0],
                        value[1],
                        `... 省略 ${value.length - 3} 个坐标点 ...`,
                        value[value.length - 1]
                    ];
                } else {
                    simplified[key] = value;
                }
            }
            // 特殊处理：SerializedMask 序列化字符串
            else if (key === 'SerializedMask' && typeof value === 'string') {
                if (value.length > 20) {
                    simplified[key] = value.substring(0, 20) + '... (已省略)';
                } else {
                    simplified[key] = value;
                }
            }
            // 递归处理其他字段
            else {
                simplified[key] = simplifyJSON(value);
            }
        }
        
        return simplified;
    }
    
    // 基础类型直接返回
    return obj;
}

/**
 * 切换视图模式（完整 <-> 简洁）
 * 功能：
 * 1. 切换 appState.viewMode
 * 2. 更新按钮文本
 * 3. 重新渲染结果
 */
function onViewToggle() {
    // 切换模式
    if (appState.viewMode === 'full') {
        appState.viewMode = 'compact';
        document.getElementById('viewToggleText').textContent = '切换为完整视图';
        console.log('切换到简洁视图');
    } else {
        appState.viewMode = 'full';
        document.getElementById('viewToggleText').textContent = '切换为简洁视图';
        console.log('切换到完整视图');
    }
    
    // 如果有缓存结果，重新渲染
    if (appState.cachedResult) {
        displayResult(appState.cachedResult);
    }
}

// ============================================
// 步骤8：UI重置逻辑（后续步骤实现）
// ============================================

/**
 * 步骤8：UI重置逻辑
 */
// function resetUI() {
//     // TODO: 实现UI重置
// }

