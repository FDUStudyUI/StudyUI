# 文献方法辅助分析

StudyUI 将方法检索、条件核对、确定性计算和结果追溯连接起来。新增能力不需要安装个人 AI skill；算法、方法卡和表单随项目及 Python wheel 提供，教学示例随源码仓库提供。

## 可以直接使用的能力

| 入口 | 使用方式 | 输出 |
|---|---|---|
| 文献方法建议 | 填关键词，选择目标、信号定义及已确认的条件 | 方法候选、适用/缺条件/不适用原因、来源位置、节点参数映射 |
| FTIR/Raman 数据处理 | 在原节点选择 AsLS、SNV 或 SG 导数 | 原始、基线、平滑、导数、处理曲线，以及原信号尺度的峰特征 |
| PCA/PLS 化学计量学 | 选择波段列、样品列、train/test 划分列及成分数 | 逐样品得分、PLS 预测和残差、测试指标、训练折记录 |
| 分步分析与局部重算 | 选择“分组对照”或“光谱”任务，填列名与参数 | 分组结果、步骤状态、耗时、复用原因、原始与处理分支的中间结果 |
| 结果与文献证据 | 选择结果列，可选文献方法卡，分别填写解释和推测 | 逐行结果引用、表格指纹、来源及分类型结论卡 |
| 聊天中的方法建议 | 直接询问某种数据适合什么分析方法 | Agent 可调用离线 `recommend_analysis_methods` 工具，无需传文件到外部服务 |

方法卡界面初始只显示关键词、目标、信号、坐标单位、信号单位和候选数。选择目标后展开相关条件；未知条件保留未知。高级 JSON 继续用于旧流程兼容，四条新示例均使用表单。

## 四条教学工作流

在 `packages/materials-quality/examples/paper_flows/` 导入以下 JSON。示例内嵌合成数据，导入后直接运行最右侧的“分析报告生成”，无需绝对文件路径或模型密钥。

1. **01_spectrum_evidence.json**：文献建议与实际计算分别接入报告。AsLS 扣除背景后提取约 720 nm 的合成峰，结论卡保留峰位、FWHM 和面积对应的结果单元格。
2. **02_pls_holdout.json**：40 个合成样品，30 个训练、10 个测试；训练集内部三折选择成分数。查看化学计量学节点的“结果与追溯”中的 `metrics.test`，以及“结果表格”中的 prediction/residual。
3. **03_local_repair.json**：原始分组统计与标准化分支独立。修改标准化方法只影响标准化及下游；查看步骤指纹和 `intermediate_results` 比较原始、处理后的结果。
4. **04_incompatible_method.json**：任务为比较暗场绝对强度，明确不允许丢失强度信息；SNV 显示 blocked，不产生执行映射。

同一个原生组件实例会保留受完整性校验的执行记录。若 Langflow 重新创建组件实例、服务重启或重新导入图，则安全地重新计算；不保证跨服务器重启复用。可运行 `python examples/analysis_plan_demo.py` 精确观察三步初算、两步修订、零步重复的过程。

## 论文方法如何转化为功能

| 来源 | 借鉴的设计 | 本项目实现与区别 |
|---|---|---|
| [LUMIR，arXiv v2](https://arxiv.org/abs/2507.21471v2) | 从文献方法到受控科学函数 | 本地、可追溯的方法卡和条件检查；没有复制未明确许可的仓库代码，也没有导入未核验的文献库 |
| [Data Interpreter](https://arxiv.org/abs/2402.18679) | 分层任务、依赖关系与执行反馈 | 小规模、纯计算任务图，显式修订、依赖失效和有条件复用；不让模型自行扩大物理窗口 |
| [SciLink](https://arxiv.org/abs/2508.06569) | 定量观察与文献解释关联 | 结果引用、方法来源、解释及推测分开；未实现自动新颖性评分或 DFT 理论闭环 |
| [BLADE](https://aclanthology.org/2024.findings-emnlp.815/) | 检查中间分析决策 | 预先指定期望的条件选择、数据隔离及失败修订用例；不宣称运行了 BLADE 官方基准 |

11 张初始方法/任务卡包括 SG 平滑、一阶/二阶导数、AsLS、SNV、PCA、PLS、峰检测和积分，以及尚未开放执行的 MSC/NMF。证据主要是原始算法资料及官方科学库文档，包含来源版本、位置、短摘录和核查范围。它们是可用方法依据，**不是 11 份已验证适用于当前材料的实验配方**。详见 [方法卡来源](../packages/materials-quality/docs/method-card-evidence.md)。

## 科学与执行约束

- SG 导数要求等间距真实坐标、合理窗口和明确单位。输出导数单位包含坐标的相应幂次。峰位、峰宽和面积继续使用导数及归一化前的平滑信号。
- AsLS 保留估计基线与原始信号，使用索引二阶差分惩罚；宽峰是否被过度扣除仍需检查参数敏感性。
- SNV 要求确认允许去除绝对强度；零方差光谱拒绝执行。其处理值不能用作原始绝对强度或面积。
- PCA/PLS 的中心化、缩放和模型只在训练集拟合，交叉验证每折重新拟合。同一样品或重复组不得跨训练/测试两侧。PLS 当前为单目标，要求输入有限数值；未提供独立测试集时不报告测试性能。
- 任务图只允许预登记的无副作用运算；文件写出、网络、LLM、任意 Python 以及通用 Langflow 图均不纳入结果复用。预算限制步骤和调用次数，不会强制中断正在运行的单个科学函数。
- 复用校验包括输入值、单位及元数据、参数、依赖结果、实现源码及库版本。结果被修改后不能继续当作有效缓存。
- 结论卡的 `cell_verified` 仅表示与上游表单元格一致，不代表仪器准确、物理模型正确或文献解释已证实。缺失测量不会转成零。

## 复现与评测

验收范围、公开数据对照及本机环境限制见 [验证记录](evidence-guided-validation.md)。

在 `packages/materials-quality` 中安装 `.[langflow,science,dev]` 后运行：

```powershell
python -m scripts.build_science_components
python -m scripts.build_paper_examples
python -m pytest tests/test_paper_workflows.py tests/test_science_method_cards.py tests/test_science_analysis_plan.py tests/test_research_plan.py tests/test_result_evidence.py tests/test_agent_method_recommend.py -q
python -m scripts.evaluate_paper_methods --output artifacts/paper-evaluation/synthetic.json
python examples/analysis_plan_demo.py
```

四条示例测试会重新加载序列化后的图、执行节点连接、核对数值及导出文件。真实浏览器验收脚本为 `scripts.ui_paper_acceptance`，在隔离的本机 Langflow 服务上执行上传、下拉操作、运行和查看结果。

公开数据评测可额外指定一个含 `corn/` 和 `tecator/` 的数据目录：

```powershell
python -m scripts.evaluate_paper_methods --data-root DATA_DIRECTORY --output artifacts/paper-evaluation/public-data.json
```

需要的文件为 `corn/corn_data.npy`、`corn/protein_label.npy`、`tecator/tecator_data.npy`、`tecator/tecator_label.npy`。读取时禁用 pickle。数据文件不随本提交重复分发；输出记录 SHA-256、显式行划分、预测误差和数值对照。已核查的数据快照来自 [LUMIR 固定版本的数据目录](https://github.com/Jeff11272/LLM-Agent-for-Automated-Infrared-Spectral-Reasoning/tree/3184ec402afd293997e79f41184016e7c3db3449/data)。本次核查的 Corn 快照对应 m5 单仪器数据；脚本接受其他同名数组时不能自动确认仪器和真实样品身份，使用行号生成的 ID 不构成真实试样独立性的证明。

数值对照是独立调用相同 sklearn 算法，用于发现接入错误；不是算法性能创新，也不是在线 LLM 对照实验。测试集扰动检查要求训练模型完全不变。合成任务和公开数据分别报告，不混合成一个“智能体准确率”。
