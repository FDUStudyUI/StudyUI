# StudyUI 适用范围、材料典型任务与技术限制说明

> 本文档由 `materials_quality.assets.scope_doc.render_scope_and_limitations_markdown()` 直接从科学资产图谱生成，确保文档边界与代码登记资产保持一致。

## 一、当前纳管资产概览

- **已登记科学计算组件（T）**：90 个
- **材料方法与文献知识卡（K）**：41 张
- **典型材料任务工作流规范（W）**：5 类
- **内置科研技能包（S）**：14 个
- **带来源与哈希的真实仪器案例（D）**：9 份
- **声明式研究角色（R）**：4 个
- **资产图谱关系边**：383 条（校验错误数：0）

## 二、五大典型材料任务的适用范围与明确不支持场景

### 锂电池充放电与循环衰减（`W:protocol.battery`）

- **状态**：已支持一键协议编译（表单/对话直出原生节点）；主算子：`materials.battery_cycles`
- **适用范围**：
  - 带明确 cell_id、正整数 cycle 及容量单位（Ah/mAh）或带 phase（charge/discharge/rest）标记的时间—电流充放电曲线。
  - 用于单电芯容量积分、同电芯基准循环保持率（retention_pct）与配对库仑效率计算。
- **明确不支持 / 需换方法场景**：
  - 仅有单次循环的数据不可外推长循环寿命保持率或衰减拐点。
  - 不同倍率（C-rate）、温度或截止电压混排且未分组时，不可直接横向比较循环衰减速率。
  - 充电与放电未按先充后放顺序配对时，不可报告有效配对库仑效率。
- **已知技术限制**：
  - 当前确定性节点聚焦电化学循环容量与保持率统计，不含 dQ/dV 微分容量峰归属或 EIS 等效电路拟合。
  - 跨电芯归一化被禁止，每颗电芯均以自身基准循环计算保持率；异常循环保留原因标记而不静默丢弃。
- **标准与方法依据**：[IEC 62660-1: Secondary lithium-ion cells — Performance testing](https://www.iec.ch/)；[BIPM SI Brochure — Electric charge and derived units (Ah / C)](https://www.bipm.org/en/publications/si-brochure)

### 力学性能（`W:protocol.mechanics`）

- **状态**：已支持一键协议编译（表单/对话直出原生节点）；主算子：`materials.mechanics`
- **适用范围**：
  - 单试样单调拉伸工程应力—应变曲线（已明确应变单位 fraction/% 与应力单位 Pa/kPa/MPa/GPa）。
  - 具备明确弹性拟合区间（至少 3 个有效测量点）与正偏移应变定义（如 0.2% 屈服偏移）。
- **明确不支持 / 需换方法场景**：
  - 循环加载/卸载滞回曲线未先分段时不可直接按单调拉伸协议拟合模量。
  - 未提供原截面积或标距的原始载荷—位移数据不可直接冒充工程应力—应变。
  - 未确认试样断裂依据时不可将曲线末点自动报告为断裂延伸率。
- **已知技术限制**：
  - 不同弹性选段可能产生显著模量差异，较高 R² 本身不证明测量链或引伸计校准正确。
  - 协议默认计算工程应力/应变，不自动执行真应力—真应变或颈缩后的本构反演。
  - 单试样采样点不构成独立试样重复；批次对比须使用试样级特征汇总。
- **标准与方法依据**：[BIPM SI Brochure](https://www.bipm.org/en/publications/si-brochure)；[ASTM E8/E8M: Tension Testing of Metallic Materials](https://www.astm.org/e0008_e0008m.html)；[ASTM E111: Young's Modulus, Tangent Modulus, and Chord Modulus](https://www.astm.org/e0111.html)

### 光谱特征（`W:protocol.spectra`）

- **状态**：已支持一键协议编译（表单/对话直出原生节点）；主算子：`materials.spectra`
- **适用范围**：
  - 单调递增坐标轴（nm、cm^-1、eV、Hz）上的拉曼、红外吸光度或光致发光正峰光谱。
  - 显式声明基线策略（none/linear）与信号单位下的正突出度阈值。
- **明确不支持 / 需换方法场景**：
  - 透射率（transmittance）谱线的吸收谷不可直接使用正峰提取，需先转换或选用谷检测。
  - 未提供激发波长时不可将原始波长直接换算为拉曼位移。
  - 不同曝光时间或未做参考校正的光谱不可直接比较绝对峰强。
- **已知技术限制**：
  - 候选峰位与面积为描述性信号特征，不构成已验证的化学键或振动模式归属。
  - 端点线性背景对宽荧光包络存在偏差，严重重叠峰需额外分峰拟合与残差核验。
- **标准与方法依据**：[BIPM SI Brochure](https://www.bipm.org/en/publications/si-brochure)；[SciPy find_peaks: prominence, width and sampling conditions](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html)；[SciPy Savitzky-Golay filter: window and polynomial conditions](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html)

### TG/DSC 热分析（`W:protocol.thermal`）

- **状态**：已支持一键协议编译（表单/对话直出原生节点）；主算子：`materials.thermal`
- **适用范围**：
  - 单调升温或明确分段的热重分析（TGA）与差示扫描量热（DSC）曲线，具备明确温度单位（°C/K）与质量/热流单位。
  - 用于失重台阶、DTG 速率峰及吸/放热特征峰的描述性提取与对比。
- **明确不支持 / 需换方法场景**：
  - 升降温循环未拆分为单调温区前，不可直接执行一阶导数（DTG）或热流峰积分。
  - 缺少升温速率、吹扫气氛（N2/空气）及样品质量记录时，不可直接进行动力学活化能反演或比焓定标。
  - 仪器基线漂移未提供空白坩埚参比时，不可将绝对热流值解释为标准相变焓。
- **已知技术限制**：
  - 特征温度（onset/peak）高度依赖升温速率、样品量与基线切线选取，仅在相同测试条件下可比。
  - 描述性热效应峰不直接证明分解产物化学组成，需联用质谱/红外（TG-IR/MS）等独立证据。
- **标准与方法依据**：[ASTM E1131: Standard Test Method for Compositional Analysis by Thermogravimetry](https://www.astm.org/e1131-20.html)；[ASTM E1356: Standard Test Method for Assignment of the Glass Transition Temperatures by DSC](https://www.astm.org/e1356-23.html)；[SciPy Savitzky-Golay filter: window and polynomial conditions](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html)

### XRD 表征（`W:protocol.xrd`）

- **状态**：已支持一键协议编译（表单/对话直出原生节点）；主算子：`materials.xrd`
- **适用范围**：
  - 0–180° 范围内严格递增的 2θ（deg）粉末 X 射线衍射一维扫描谱。
  - 用于背景评估、候选衍射峰提取、表观峰宽（FWHM）与面积统计。
- **明确不支持 / 需换方法场景**：
  - 缺少已知辐射波长（如 Cu Kα）时不可计算晶面间距 d 或执行 Scherrer 晶粒尺寸估计。
  - 无标准参考峰表/CIF 理论谱对照时，严禁直接输出确定性物相鉴定结论。
  - 非 2θ 坐标（如 q 空间、d 间距或弧度 rad）不可直接进入角度协议。
- **已知技术限制**：
  - 经验峰形拟合与候选峰排序不替代全谱 Rietveld 结构精修。
  - 表观峰宽包含仪器展宽贡献，未扣除标准样品仪器展宽前不可宣称真实微晶尺寸。
- **标准与方法依据**：[IUCr Online Dictionary: Bragg's law](https://dictionary.iucr.org/Bragg%27s_law)；[SciPy find_peaks: prominence, width and sampling conditions](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html)；[IUCr Online Dictionary: Scherrer equation](https://dictionary.iucr.org/Scherrer_equation)

## 三、研究角色能力边界（Role Subgraphs）

| 角色 ID | 角色名称 | 可挂载工具数 | 适用范围 | 核心限制 |
|---|---|---:|---|---|
| `R:characterization_analyst` | 材料表征分析角色 | 16 | 力学拉伸、拉曼/红外/荧光光谱、粉末 XRD、锂电池循环与 TG/DSC 热分析等单曲线或分组表征任务。 | 默认不包含工作流删除工具与外部学术检索工具；需要文献核验时应切换至文献证据角色或规划角色。 |
| `R:data_quality_auditor` | 原始数据与质控审计角色 | 14 | 原始表格、Excel 多工作表、数值 XY 与 HDF5/NetCDF/Zarr 仪器数据的结构审查、单位契约与异常检测。 | 仅对已授权项目目录或当前会话上传文件执行只读检查，无法访问未授权路径或外部网络数据。 |
| `R:literature_reviewer` | 学术文献与方法证据角色 | 9 | CrossRef、OpenAlex、Semantic Scholar、Europe PMC、DataCite 白名单学术元数据检索与方法卡前提核对。 | 该角色为只读证据角色，不具备创建、修改、运行或删除工作流的权限。 |
| `R:workflow_planner` | 科研工作流编排与治理角色 | 19 | 跨表征方法、多分支工作流编排、工作流修复与删除管理，以及需要同时调用文献与计算的复合科研任务。 | 工具集最全，适合复杂或跨领域任务；单一领域常规分析优先交由专职角色以降低工具误选率。 |

## 四、MatOS 外部工具接入（可选）

StudyUI 以只读目录形式登记 MatOS 的 18 个工具资产（14 个外部工具 + 4 个 builtin pack）。外部工具仅通过用户安装的 `matos assets run-tool` 执行；缺少 `matos` CLI 时返回 `unavailable` 与安装提示，不会伪造成功。builtin pack 只能在 MatOS asset MCP server 内运行，StudyUI 仅登记其元数据。

| 工具资产 ID | 名称 | 调用方式 | 可用性策略 |
|---|---|---|---|
| `T:matos.agent-orchestration` | Agent Orchestration (MatOS) | `matos_asset MCP server (builtin pack)` | `matos_runtime_only`（builtin pack） |
| `T:matos.atomistic-toolchain-catalog` | Atomistic Toolchain Catalog (MatOS) | `matos assets run-tool` | `requires_matos_cli` |
| `T:matos.battery-electrochem-catalog` | Battery Electrochemistry Catalog (MatOS) | `matos assets run-tool` | `requires_matos_cli` |
| `T:matos.conda-environment-catalog` | Conda Environment Catalog (MatOS) | `matos assets run-tool` | `requires_matos_cli` |
| `T:matos.conda-environment-manager` | Conda Environment Manager (MatOS) | `matos assets run-tool` | `requires_matos_cli` |
| `T:matos.deep-research-search` | Deep Research Scholarly Search (MatOS) | `matos assets run-tool` | `requires_matos_cli` |
| `T:matos.document-parse` | Document Parse (local files) (MatOS) | `matos assets run-tool` | `requires_matos_cli` |
| `T:matos.files-core` | Files Core (MatOS) | `matos_asset MCP server (builtin pack)` | `matos_runtime_only`（builtin pack） |
| `T:matos.gemini-vision-analyze` | Gemini Vision Analyze (MatOS) | `matos assets run-tool` | `requires_matos_cli` |
| `T:matos.literature-access` | Literature Access (MatOS) | `matos assets run-tool` | `requires_matos_cli` |
| `T:matos.local-toolchain-preflight` | Local Toolchain Preflight (MatOS) | `matos assets run-tool` | `requires_matos_cli` |
| `T:matos.materials-runtime-inventory` | Materials Runtime Inventory (MatOS) | `matos assets run-tool` | `requires_matos_cli` |
| `T:matos.mlip-model-catalog` | MLIP Model Catalog (MatOS) | `matos assets run-tool` | `requires_matos_cli` |
| `T:matos.mp-query` | Materials Project Query (MatOS) | `matos assets run-tool` | `requires_matos_cli` |
| `T:matos.scip-toolchain-catalog` | SCIP Toolchain Catalog (MatOS) | `matos assets run-tool` | `requires_matos_cli` |
| `T:matos.shell-core` | Shell Core (MatOS) | `matos_asset MCP server (builtin pack)` | `matos_runtime_only`（builtin pack） |
| `T:matos.web-read` | Web/PDF Read (MatOS) | `matos assets run-tool` | `requires_matos_cli` |
| `T:matos.web-research` | Web Research (MatOS) | `matos_asset MCP server (builtin pack)` | `matos_runtime_only`（builtin pack） |

## 五、系统级技术限制与评测边界声明

1. **确定性计算与模型推理分离**：数值计算由本地已登记科学节点执行；大语言模型仅负责任务理解、参数澄清、建流编排与报告综合，不替代精确数值求解。
2. **当前不覆盖的领域计算**：系统目前聚焦材料实验表征数据质控与定量分析，不包含第一性原理计算（DFT/VASP/QE）、分子动力学集群调度（LAMMPS）或全谱 Rietveld 结构精修。
3. **评测三维度解耦原则**：
   - **工作流构建成功率**：衡量智能体在真实仪器数据上构建合法可执行流程的比例。
   - **计算结果可重复性（独立维度）**：衡量固定工作流在冷启动多进程与复现包重跑下结果表哈希与数值的一致性。
   - **所选方法正确性（独立维度）**：衡量方法选型、物理前提契约、越界拦截以及材料专家评审质量；运行成功或结果可重复**不等于**方法选择正确。
4. **当前已内置真实仪器验证数据**：共 9 份公开仪器文件（带 DOI 与 SHA-256 校验），覆盖金属拉伸、矿物 XRD 与聚合物 Raman，后续按计划扩充锂电池循环与热分析真实数据集及越界反例集。
