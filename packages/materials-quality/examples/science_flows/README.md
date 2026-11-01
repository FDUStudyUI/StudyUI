# 九份可导入的材料科学工作流

在同一 Python 环境安装项目的科学计算和 Langflow 依赖，启动 Langflow 后，选择导入流程，打开下表任一编号 JSON。运行最右侧的“分析报告生成”节点即可执行整张图。最终节点的“结果与追溯”包含 HTML 报告文件路径，各上游节点可查看自己的表格、参数和警告。服务器运行 Langflow 时，文件路径位于服务器上。

每个 JSON 自带样例代码与合成数据。起点在运行时解码内嵌数据，校验文件 SHA-256，写入本机新建的临时目录。流程里的 `@asset:文件名` 在运行时解析。各文件可单独复制到另一台已安装本项目的机器。OCR 使用本机 RapidOCR ONNX 模型，文献示例使用内嵌段落。

0.4.0 起，九份流程的科学节点均采用原生表单，包括列、单位、区间及规则表，无需编辑 JSON。
模型示例明确选择“已有模型”预测；高级设置仍保留旧配置兼容入口。操作说明见[表单使用指南](../../docs/node-usability.md)。

| 流程 | 连线与可以核对的输出 |
|---|---|
| [01 表格整理](01-tables.json) | CSV 与 SQLite → 显式类型、缺失值、单位、选列 → 按样品合并 → 归一化 → CSV。三行归一化值依次为 0、0.5、1。 |
| [02 PDF 与定宽文本](02-documents.json) | PDF 接入 → 原生文本和表格提取。定宽文本另一路转为 CSV，同一报告汇集两种来源。 |
| [03 图像提取](03-images.json) | 图像接入 → OCR、表格识别。标定曲线另一路输出 101 个坐标点，满足 y = 10x。 |
| [04 仪器与光谱](04-spectra.json) | XY 仪器输入 → 用户参考全谱拟合，幅度系数为 2、3。合成振动谱 → 扣基线、积分、归一化和叠加图，峰面积约 5.0133。 |
| [05 拉伸与 DSC](05-mechanics-thermal.json) | 拉伸表 → 弹性拟合和曲线图，弹性模量为 200000 MPa。DSC 文件 → 单位换算与积分，结果约为 150.398 J/g。 |
| [06 显微与 EDS](06-morphology.json) | 图像 → 标定孔隙面积 → Excel。32 个前景像素占图像面积的 8%。另一分支读取外部定量的 EDS 百分比。 |
| [07 分组统计](07-statistics.json) | 同一独立样品表 → 描述统计、分布、相关、ANOVA → Tukey 组间比较及性能图。三个实验组产生三组两两比较。 |
| [08 建模与评估](08-model.json) | 明确划分建模行与外部样例 → 保存模型 → 从模型文件预测 → 比较实测和预测值并制图。未参加训练的 10 行满足合成真值 y = 2x + 3。 |
| [09 文献证据](09-literature.json) | 本地检索 → 元数据、逐字抽取 → 单位对齐 → 来源登记与证据摘要。两条数据在同一 MPa 尺度下仍有一处数值冲突。 |

44 个科学操作全部出现在至少一张已验证的图中。每份图选择一条或多条的方法路径，其他子方法的配置和测试见对应的领域手册。[执行记录](verification.json)

从 `packages/materials-quality` 目录运行以下命令可复核已经交付的 JSON。它会按顺序导入和执行流程，核对来源链、合成真值、输入哈希及导出文件。

```powershell
$env:PYTHONUTF8 = '1'
$env:MPLBACKEND = 'Agg'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
python -m scripts.build_science_examples --verify-only
```

核查一项可追加 `--case 08-model`。在代码仓库中运行 `python -m scripts.build_science_examples --verify` 会用当前代码重新构建九份 JSON、逐一回读执行，并更新执行记录。Python 测试也可调用 `scripts.build_science_examples.verify_flow(path)` 或 `verify_committed_flows(directory)`。
