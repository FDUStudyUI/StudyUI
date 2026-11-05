---
name: studyui-dna-origami-plasmonics
description: 分析 DNA origami 定位单染料的等离激元纳米间隙、nanoparticle-on-mirror、暗场/Raman/发射光谱与单颗粒时间序列；用于等离激元增强、纳米腔或该类论文公开数据复核。
metadata:
  version: "1.3.0"
  domain: "plasmonic-nanocavity-spectroscopy"
  triggers: "DNA origami|DNA-origami|DNAo|single dye|single-dye|single molecule plasmonic|plasmonic nanogap|nanoparticle-on-mirror|NPoM|picocavity|dark-field Raman|plasmonic force|nanotractor|DNA折纸|DNA origami|单染料|单分子等离激元|等离激元纳米间隙|金纳米颗粒|金镜纳米腔|暗场拉曼|单颗粒光谱|DNAo|光致等离激元力"
---

# DNA Origami 等离激元单染料数据

1. 把该研究看作多层证据链：DNA origami 与染料构型/定位 → nanoparticle-on-mirror 几何和间隙 → 暗场共振与照明 → 发射/Raman 信号 → 时间演化/结构变化。每条结论都应对应公开数据文件、图表、实验条件或论文段落，不跨层推断。
2. 论文的具体结论之一是单染料 NPoM 的发射可被分子与金属的非弹性 Raman 散射主导，简单的“Purcell 增强荧光”解释并不充分。不得把所有窄峰都标成荧光、把强度增加自动解释为量子产率增强，或只凭峰图宣称单分子机制。
3. Cambridge 原始数据记录说明数据来自自建暗场与 Raman 显微镜，并链接研究数据包。先下载/检查其 README、文件树、文件元数据和列定义；未经实际检查，不猜测其中曲线、组别、列含义、测试样本数或实验是否完全原始。
   - 仓储包可能同时包含仪器 HDF5、图表 Source Data CSV/XLSX、图片及脚本。用户要求原始数据时，优先从原 HDF5 工作，不得用图表导出的 CSV 替代；先核对哈希、HDF5 组/数据集层级、数组形状、仪器属性、背景/参考记录及采集顺序，再按证据标注原始或派生层级。
   - 名称含 `histogram` 的 HDF5 仍须检查实际内部结构；既不能只凭名字判为汇总数据，也不能因其为 HDF5 就宣称未处理。层级或元数据不明时，将其标为待核实。
   - Harness 返回 `instrument_structure` 时，直接用其中受限的路径模式、shape、dtype 和计数来规划导入，不需要、也不得把完整 browse 表或 attrs 值送入模型。不要把纯本机确定性读取误当成原始数据外传：确定性节点可在本机处理数组，`run_workflow` 只把 Harness 允许的摘要交给主 Agent；只有 AI 子代理节点会发送其被连接的上游数据，且需通过单次审批。
   - `ScienceIoInstrumentImport` 的 HDF5/NetCDF/Zarr `read` 必须使用真实 `dataset_path` 和长度匹配的一维 `x_axis_path`；二维信号还必须明确 `spectrum_axis`，并使用匹配的 `group_axis_path` 保留唯一曲线标识。节点不会推断坐标或自动展平。不能从文件结构中核实坐标轴/标识数组时，不要构造假轴或反复试探配置；说明当前工具缺少的输入前提。
   - 若模型上下文缺少坐标语义，不要只因 read 模式处理原始数组就放弃本地确定性分析；先查目录中真实的仪器读取/统计节点与轴配置要求。只有当轴、单位、行列语义无法由本机可核验来源或确定性节点确认时，才停止相应的定量谱分析并如实报告，不得猜测。
   - HDF5 层级导出表只在用户要求本地清单或确有复核需要时创建；它可能包含 attrs 元数据。导出必须留在项目本地，报告不得复述 attrs 原文或测量数组。
4. 优先按文件/记录映射样品、粒子、DNAo/染料条件、照明功率、时间和测量模式。分开暗场光谱、Raman/发射光谱、AFM/DLS 图像与控制实验，不把不同仪器量放在同一数值列或坐标轴。
5. 读取论文/SI 中的激发波长、功率、曝光、时间序列、样品条件和控制组；只有当原始文件及记录匹配时才把论文实验条件映射到数据。文中某些测试采用 633 nm 共振激发，但不能据此假定仓储全部文件都在该条件下采集。
6. 对每颗粒/每个时间序列保留身份和采集顺序。波长像素、counts、counts per second、功率归一化、背景扣除和光谱积分只按说明解析；把每个波长点当独立样本属于伪重复。
7. 对照组应按原文实验设计分别标识（例如有/无 DNA origami、不同染料、低功率、照射前后）；不要混并对照或以缺少某组的数据代替它。无法从原始数据匹配组别时降级为描述性结果。
8. 区分逐粒子轨迹、组均值、结构变化图像和光谱峰位置。波长漂移或强度变化可作为可观测现象；“等离激元力导致金原子重排”是机制解释，需论文学术证据及对应控制，不由单个 StudyUI 曲线图独立证明。
9. StudyUI 节点路线先检查文件导入、光谱分析、批量曲线、时序和可视化端口。如果现有节点无法表示粒子层级、时间序列或必要光谱单位，应做可验证子集并披露覆盖；不可伪造专用等离激元模拟节点。
   - 对 HDF5 先查真实存在的仪器/数组导入节点，优先保留 scan → particle → measurement 层级和来源顺序；若只能读出压平预览或某些数组类型未支持，不要把预览当成全量结果。
10. 报告至少写明数据仓储 DOI/记录号、文件哈希、读取文件/曲线覆盖、粒子/样本计数依据、谱线单位/激发条件的证据、预处理、对照组映射、观察结果和不能由数据单独确认的结论。

## 参考

- [Cambridge Research Data：该论文的支持数据](https://www.repository.cam.ac.uk/items/5fb76156-d930-455c-98c5-3ee330e02fe7)：公开源数据记录与显微镜来源说明。
- [开放获取论文全文](https://pmc.ncbi.nlm.nih.gov/articles/PMC10347698/)：DNAo 定位的 NPoM、发射/Raman 解释、控制实验和照明效应。
- [论文 DOI](https://doi.org/10.1021/acs.nanolett.3c01016)：Nano Letters 23(13), 5959–5966 (2023)。
