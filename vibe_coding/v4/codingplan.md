## Ceph 可视化迭代开发计划

### 目录结构（目标态）
- `pipelines/ceph/ceph_pipeline.py`：推理与报告生成入口（调用链保持）。
- `pipelines/ceph/utils/ceph_report.py`：测量计算（仅可能复用/暴露几何函数）。
- `pipelines/ceph/utils/ceph_report_json.py`：JSON 组装，挂接 `Visualization` 字段。
- `pipelines/ceph/utils/ceph_visualization.py`：新增，可视化构建与几何辅助（单文件 <500 行）。
- `example/ceph_output.json`：示例输出，对齐新增字段做对比验证。

### 受影响模块与适配
- `ceph_report.py`：可能复用或补充 `_project_point_onto_line` 等几何函数，保持测量值逻辑不变。
- `ceph_report_json.py`：移除 Group 逻辑，接入 `visualization_map`，格式化坐标为两位小数，失败时置 `Visualization: null`。
- `ceph_visualization.py`（新增）：根据测量名和 landmarks 生成 `VisualizationPayload`，未覆盖项返回 `None` 占位。
- `ceph_pipeline.py`：调用链保持，仅确认新参数默认开启可视化时不破坏现有输出。

### 渐进式小步迭代步骤
1. 基线梳理与样例对齐  
   - 行动：阅读 `example/ceph_output.json`，确认现有字段结构与测量命名；梳理 PRD/LDD 中需支持的测量列表。  
   - 交付：一份测量名对照清单，用于后续可视化分派；确保不改动代码，程序可运行。

2. 新增可视化模块骨架  
   - 行动：创建 `pipelines/ceph/utils/ceph_visualization.py`，定义 `build_visualization_map`、`build_single`、`_project_point_onto_line`、`_format_point` 框架，未实现测量返回 `None`。  
   - 交付：模块可被 import，返回空占位，现有流程不报错。

3. 实现核心测量可视化（迭代1）  
   - 行动：在 `build_single` 中覆盖 PRD/LLD 列表：`ANB/SNA/SNB`、`PoNB_Length`、`GoPo_Length`、`Distance_Witsmm`、`FH_MP_Angle`、`U1_SN_Angle`、`IMPA_Angle`。  
   - 细节：按文档添加虚拟点计算（如垂足）与 Elements（Style/Role），坐标保留两位小数。  
   - 交付：对应测量返回 `VisualizationPayload`，其余仍为 `None`。

4. 接入 JSON 组装  
   - 行动：在 `ceph_report_json.generate_standard_output` / `_build_measurement_entry` 中调用 `build_visualization_map`，注入 `Visualization` 字段，移除 Group 逻辑。  
   - 交付：生成的 JSON 结构新增 `Visualization`，旧字段不受影响；失败或缺数据时返回 `null`。

5. 健壮性与格式校验  
   - 行动：对虚拟点与引用一致性做判空校验；保证坐标格式 `[float, float]` 两位小数；零向量垂足返回起点。  
   - 交付：针对缺测、状态非 ok 的测量，`Visualization` 为 `null`；运行通过基本流程。

6. 回归与样例验证  
   - 行动：用当前推理输出跑一遍 `generate_standard_output`，比对生成 JSON 与 `example/ceph_output.json` 结构差异，确认新增字段符合预期。  
   - 交付：一份验证记录（差异点列表），确保应用可运行。

### 实现流程（Mermaid）
```mermaid
flowchart TD
    A[Landmarks & Measurements] --> B[ceph_visualization.build_visualization_map]
    B --> C[Visualization Map{name: payload|None}]
    A --> D[ceph_report_json._build_measurement_entry]
    C --> D
    D --> E[AllMeasurements 带 Visualization]
    E --> F[generate_standard_output 输出 JSON]
```

