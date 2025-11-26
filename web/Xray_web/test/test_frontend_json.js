/**
 * 前端 JSON 数据测试脚本
 * 在浏览器控制台中运行此脚本来检查前端获取的 JSON 数据
 * 
 * 使用方法：
 * 1. 打开浏览器开发者工具 (F12)
 * 2. 切换到 Console 标签
 * 3. 复制粘贴此脚本并执行
 * 4. 或者直接调用 testCephJson() 函数
 */

function testCephJson() {
    console.log("=".repeat(80));
    console.log("前端侧位片 JSON 数据测试");
    console.log("=".repeat(80));
    
    // 检查是否有缓存的结果
    if (typeof appState === 'undefined') {
        console.error("✗ appState 未定义，请先提交一个侧位片任务");
        return;
    }
    
    const cachedResult = appState.cachedResult;
    if (!cachedResult) {
        console.log("⚠ 没有缓存的结果");
        console.log("请先提交一个侧位片任务并等待结果返回");
        console.log("或者手动设置: appState.cachedResult = <你的结果数据>");
        return;
    }
    
    console.log("\n✓ 找到缓存的结果");
    console.log("任务 ID:", appState.currentTaskId);
    console.log("任务类型:", appState.currentTaskType);
    
    // 检查数据结构
    if (cachedResult.status !== 'SUCCESS') {
        console.log("\n✗ 任务状态不是 SUCCESS:", cachedResult.status);
        return;
    }
    
    const data = cachedResult.data;
    if (!data) {
        console.log("\n✗ 数据为空");
        return;
    }
    
    // 检查 CephalometricMeasurements
    if (!data.CephalometricMeasurements) {
        console.log("\n✗ 未找到 CephalometricMeasurements 字段");
        console.log("可用字段:", Object.keys(data));
        return;
    }
    
    const measurements = data.CephalometricMeasurements.AllMeasurements || [];
    console.log(`\n找到 ${measurements.length} 个测量项`);
    
    console.log("\n" + "-".repeat(80));
    console.log("测量项 Level 值详情:");
    console.log("-".repeat(80));
    
    measurements.forEach(m => {
        const label = m.Label || 'N/A';
        const level = m.Level;
        const levelType = typeof level;
        
        let valueStr = '';
        if (m.Angle !== undefined) {
            valueStr = `Angle=${m.Angle.toFixed(2)}°`;
        } else if (m.Ratio !== undefined) {
            valueStr = `Ratio=${m.Ratio.toFixed(2)}%`;
        } else if (m.Length_mm !== undefined) {
            valueStr = `Length=${m.Length_mm.toFixed(2)}mm`;
        }
        
        console.log(`  ${label.padEnd(25)}: Level=${level} (type=${levelType}), ${valueStr}`);
    });
    
    // 验证 Level 值
    console.log("\n" + "-".repeat(80));
    console.log("Level 值验证:");
    console.log("-".repeat(80));
    
    measurements.forEach(m => {
        const label = m.Label || '';
        const level = m.Level;
        let expectedLevel = null;
        let actualValue = null;
        
        if (label === 'ANB_Angle') {
            actualValue = m.Angle;
            if (actualValue !== undefined) {
                if (actualValue > 6.0) {
                    expectedLevel = 1; // 骨性II类
                } else if (actualValue < 2.0) {
                    expectedLevel = 2; // 骨性III类
                } else {
                    expectedLevel = 0; // 骨性I类
                }
            }
        } else if (label === 'FH_MP_Angle') {
            actualValue = m.Angle;
            if (actualValue !== undefined) {
                if (actualValue > 33.0) {
                    expectedLevel = 1; // 高角
                } else if (actualValue < 25.0) {
                    expectedLevel = 2; // 低角
                } else {
                    expectedLevel = 0; // 均角
                }
            }
        } else if (label.startsWith('SGo_NMe_Ratio')) {
            actualValue = m.Ratio;
            if (actualValue !== undefined) {
                if (actualValue > 71.0) {
                    expectedLevel = 1; // 水平生长型
                } else if (actualValue < 63.0) {
                    expectedLevel = 2; // 垂直生长型
                } else {
                    expectedLevel = 0; // 平均生长型
                }
            }
        }
        
        if (expectedLevel !== null) {
            const status = level === expectedLevel ? '✓' : '✗';
            const valueStr = actualValue !== null ? actualValue.toFixed(2) : 'N/A';
            console.log(`  ${status} ${label.padEnd(25)}: 期望 Level=${expectedLevel}, 实际 Level=${level}, 值=${valueStr}`);
        } else {
            console.log(`  ? ${label.padEnd(25)}: Level=${level} (无法验证)`);
        }
    });
    
    // 打印完整的 CephalometricMeasurements JSON
    console.log("\n" + "=".repeat(80));
    console.log("CephalometricMeasurements 完整 JSON:");
    console.log("=".repeat(80));
    console.log(JSON.stringify(
        { CephalometricMeasurements: data.CephalometricMeasurements },
        null,
        2
    ));
    
    // 复制到剪贴板的提示
    console.log("\n" + "-".repeat(80));
    console.log("提示: 可以使用以下命令复制完整 JSON 到剪贴板:");
    console.log("  copy(JSON.stringify(data.CephalometricMeasurements, null, 2))");
    console.log("-".repeat(80));
    
    return {
        measurements: measurements,
        data: data.CephalometricMeasurements
    };
}

// 自动运行（如果已经有缓存的结果）
if (typeof appState !== 'undefined' && appState.cachedResult) {
    console.log("检测到缓存的结果，自动运行测试...");
    testCephJson();
} else {
    console.log("使用方法:");
    console.log("  1. 提交一个侧位片任务");
    console.log("  2. 等待结果返回");
    console.log("  3. 运行: testCephJson()");
}

