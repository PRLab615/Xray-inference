你好！我是你的产品经理搭档。我非常理解你的需求：**做减法**。

你希望剥离掉“分组”等非核心逻辑，聚焦于\*\*“点击某个测量值 -\> 后端告诉前端画几条线”\*\*这一最本质的交互。这个需求非常合理，它能让前后端的耦合度降到最低，同时保证了核心功能（可视化诊断依据）的闭环。

虽然你提到的示例是虚拟的（woc/aoc），但逻辑是通用的：**一个测量项 = 一组线段的集合**。

基于“后端计算精度、前端负责渲染”的原则，我保留了 `VirtualPoints`（为了处理垂线等复杂情况），但移除了所有分组逻辑，输出了这份精简版 PRD。

-----

````markdown
# Product Requirement Document: Cephalometric Visualization (Simplified)

## 1. 目标
在侧位片测量报告的 JSON 输出中，新增 **可视化绘图指令 (Visualization)** 字段。
前端只需响应点击事件，读取该字段并绘制线段集合，无需关心分组或复杂的医学定义。

## 2. 核心原则
1.  **后端驱动几何**：所有点位（包括垂足、投影点）坐标由后端计算，保证精度。
2.  **前端傻瓜渲染**：前端不处理业务逻辑，只负责画线（实线/虚线、颜色映射）。
3.  **原子化**：每个测量项自带完整的绘图指令，不依赖外部配置。

## 3. 涉及文件
- `pipelines/ceph/utils/ceph_report.py` (计算逻辑：计算虚拟点、定义线段)
- `pipelines/ceph/utils/ceph_report_json.py` (数据组装：注入字段)

## 4. 数据协议 (JSON Schema Change)

在 `CephalometricMeasurements.AllMeasurements` 的数组项中，仅新增 `Visualization` 一个字段。

### 4.1 结构定义

```json
{
  "Label": "PoNB_Length",  // 现有字段
  "Value": 4.5,            // 现有字段
  "Level": 1,              // 现有字段 (用于前端判断颜色：0=绿, 1/2=红)
  
  // --- [新增] 唯一的绘图指令字段 ---
  "Visualization": {
    // 1. 虚拟点字典 (仅当该测量项需要垂足/投影点时存在，否则为 null)
    // 坐标系：原图像素坐标，保留2位小数 [x, y]
    "VirtualPoints": {
      "v_pog_on_nb": [1245.55, 890.12]
    },
    
    // 2. 线段集合 (前端遍历此数组绘制即可)
    "Elements": [
      // 线段 A: 参考线 (如 N-B)
      {
        "Type": "Line",
        "From": "N",                // 引用全局 Landmarks 的 Key
        "To": "B",                  // 引用全局 Landmarks 的 Key
        "Style": "Solid",           // "Solid" (实线) | "Dashed" (虚线)
        "Role": "Reference"         // "Reference" (参考-细/灰) | "Measurement" (主体-粗/高亮)
      },
      // 线段 B: 测量线 (如 Pog 到 垂足)
      {
        "Type": "Line",
        "From": "Pog",
        "To": "v_pog_on_nb",        // 引用上方 VirtualPoints 的 Key
        "Style": "Dashed",
        "Role": "Measurement"
      }
    ]
  }
}
````

## 5\. 详细修改清单

### 5.1 文件: `pipelines/ceph/utils/ceph_report.py`

#### 5.1.1 基础设施建设

1.  新增辅助函数 `_project_point_onto_line`：用于计算垂足坐标。

#### 5.1.2 测量逻辑改造

修改各个 `_compute_XXX` 函数，使其返回结构中包含 `visualization` 字典。

**典型改造示例：**

1.  **ANB 角 (及 SNA, SNB)**

      * 不需要 `VirtualPoints`。
      * **Elements**:
          * (S -\> N): Solid, Reference
          * (N -\> A): Solid, Reference
          * (N -\> B): Solid, Reference

2.  **PoNB\_Length (点到线距离)**

      * **VirtualPoints**: 计算 `v_pog_on_nb` (Pog 在 NB 线上的垂足)。
      * **Elements**:
          * (N -\> B): Solid, Reference
          * (Pog -\> v\_pog\_on\_nb): Dashed, Measurement

3.  **Wits (双投影距离)**

      * **VirtualPoints**:
          * `v_a_on_fh`: A 在 FH 平面垂足
          * `v_b_on_fh`: B 在 FH 平面垂足
      * **Elements**:
          * (Po -\> Or): Dashed, Reference (FH平面)
          * (A -\> v\_a\_on\_fh): Dashed, Measurement
          * (B -\> v\_b\_on\_fh): Dashed, Measurement

4.  **下颌平面角 (FH-MP)**

      * **Elements**:
          * (Po -\> Or): Dashed, Reference
          * (Go -\> Me): Solid, Reference

*(其余测量项以此类推，仅需定义构成该测量的几何线段即可)*

### 5.2 文件: `pipelines/ceph/utils/ceph_report_json.py`

#### 5.2.1 组装逻辑

修改 `_build_measurement_entry` 函数：

1.  移除所有关于 `Group` 的逻辑。
2.  提取 `payload` 中的 `visualization` 数据。
3.  格式化处理：
      * 确保 `VirtualPoints` 坐标转为 `[float, float]` (保留2位小数)。
      * 若测量计算失败或无可视化定义，`Visualization` 字段返回 `null`。

## 6\. 开发自测点 (Checklist)

1.  **坐标准确性**：虚拟点坐标必须基于原图尺寸，禁止前端进行二次缩放计算。
2.  **空值健壮性**：当 `Visualization` 为 `null` 时，前端不应报错。
3.  **引用一致性**：`From`/`To` 字段的值必须要么在 `Landmarks` 列表中存在，要么在同级的 `VirtualPoints` 中定义。

<!-- end list -->

```
```