# 材料数据质量检查：Langflow 自定义节点

六个检查节点、一个共享规则与追溯节点和一个汇总节点，按 Langflow 原生 `Component` / `DataFrame` /
`Data` / `Message` 接口实现。检查在本地 Python 中执行，不调用大模型、无需 API Key，
不删除、不插值、不换算或覆盖原数据。

本包对应 `工作流节点.md` 中的数据质量检查首批功能，不包含 XRD、SEM、物相鉴定、
模型训练或数据修复。统计离群点是待研究者复核的发现，不等同于错误实验。

## 兼容版本

- 初始验证目标：Python 3.10、LFX 1.13.0（Langflow 1.13.x 的组件与图执行运行时）、pandas 2.x。
- Pint 固定为 0.24.4，保留 Python 3.10 兼容性。
- 团队实际 Langflow 版本尚待确认。其他版本须运行测试及示例流程后再声明兼容。
- 这里同时提供真实运行时加载/执行测试；浏览器画布的视觉验收单独进行。

## 安装与运行测试

在组件包根目录执行（团队仓库中先 `cd packages/materials-quality`，PowerShell）：

```powershell
$env:PYTHONUTF8 = "1"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[langflow,dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src components tests scripts examples
```

需要固定依赖时，先 `pip install -r requirements.lock`，再 `pip install -e .`。

`langflow` extra 安装的是用于测试的 `lfx==1.13.0`，不安装网页编辑器。
Windows 中文路径配合 Python 3.10 的 editable 安装时，需保留 `PYTHONUTF8=1`，
以正确读取 UTF-8 `.pth` 路径；也可以使用普通安装 `pip install ".[langflow,dev]"`。
要使用网页编辑器，在同一虚拟环境安装团队确认的 Langflow 版本。
对于本包当前验证目标，可安装 `langflow==1.13.0`：

```powershell
.\.venv\Scripts\python.exe -m pip install "langflow==1.13.0"
$env:LANGFLOW_COMPONENTS_PATH = (Resolve-Path .\components).Path
.\.venv\Scripts\python.exe -m langflow run
```

进入组件菜单的 `materials_quality` 分类。应看到下表八个节点。
`LANGFLOW_COMPONENTS_PATH` 指向分类文件夹的**父目录**，不是某个 `.py` 文件。
本包必须安装在运行 Langflow 的同一个 Python 环境，仅复制组件文件不够。
不需要修改 Langflow 仓库或重建其前端。

## 节点及输入

六个检查节点都接收 `输入表格`，并同时提供三个输出端口：

- **原始表格**：值、顺序、索引不变的副本，便于串联后续节点。
- **问题明细**：每条发现所在列、零基行位置、原始索引、依据和严重程度。
- **检查报告**：完整计数、参数、指标、有限条明细和覆盖范围。

| 节点 | 关键配置 | 检查内容 |
|---|---|---|
| 材料数据·共享规则与追溯 | 共享规则 JSON、规则版本、来源声明 | 绑定数据指纹；六个检查连接同一上下文 |
| 材料数据·结构检查 | 必需字段 JSON、字段别名 JSON | 缺失字段、多个候选别名；不重命名 |
| 材料数据·缺失检查 | 检查列、缺失标记、可选分组 | 缺失数量和比例、行位置、缺失模式 |
| 材料数据·类型格式检查 | 字段类型规则 JSON | number、integer、string、boolean、datetime、category |
| 材料数据·单位检查 | 原始单位、目标量纲单位、检查列 | 量纲兼容、混合单位、未声明或无法识别的单位 |
| 材料数据·重复记录检查 | 重复判定键 JSON | 整行重复或组合键重复；标记每个重复成员 |
| 材料数据·异常值标记 | 数值列、方法、范围、阈值、分组 | 明确范围、IQR、MAD，以及非数值和不足以估计的基线 |
| 材料数据·检查报告汇总 | 多个检查报告 | 汇总接入的检查，输出报告、明细和 Message 摘要 |

配置字段使用标准 JSON，不接受 Python 字典语法、单引号 JSON 或 NaN/Infinity 常量。
列名必须唯一且为非空字符串。数值规则允许能准确解析的数值字符串，但不写回类型转换。

### 共享规则与数据追溯

推荐连接方式：原始表格 → **共享规则与追溯**，该节点的原始表格、共享规则与来源两个端口分别接入六项检查，再将报告接入汇总。

- 已连接上下文时，使用共享规则，忽略节点独立规则配置；未在共享规则中配置的检查报错。
- 缺失标记贯穿缺失、类型、单位、异常检查，通过显式参数统一传入；原始表格和重复判定键保持不变。`[]` 表示空字符串也不是缺失值。
- 规则集、数据值/类型/索引/顺序、来源声明均纳入追溯；汇总拒绝混用数据集、共享规则或本地/共享模式。
- 无上下文时保留原有独立配置并自动记录表格指纹。旧纯函数报告仍可单独汇总，标记 `unverified_legacy`，不能与有追溯报告混合。
- `provenance_status=verified` 表示报告间身份和参数完整性校验通过，不代表实验真实、来源可信或材料性能合格。

完整演示见 [材料力学测试案例](examples/mechanics/README.md)，包含三份 CSV、三份可导入工作流、独立预期和人工修订记录。

### 配置示例

必需字段：

```json
["sample_id", "stress", "temperature", "date"]
```

显式别名（两个候选同时出现时报告歧义）：

```json
{"sample_id": ["样品编号", "试样号"]}
```

类型和日期格式：

```json
{
  "sample_id": "string",
  "stress": "number",
  "date": {"type": "datetime", "format": "%Y-%m-%d"},
  "phase": {"type": "category", "allowed": ["alpha", "beta"]}
}
```

单位节点的原始单位：

```json
{"stress": "MPa", "temperature": "degC"}
```

目标量纲单位：

```json
{"stress": "Pa", "temperature": "K"}
```

MPa 与 Pa 兼容，不代表数值已从 MPa 换算成 Pa；输出仍保留原值。
同一列中的 `1 MPa` 和 `1000 kPa` 会标记混合单位。
纯数字没有原始单位声明时不会凭列名猜测。`degC`、`℃`、`°C` 支持温度量纲检查。

范围检查（上下限包含在允许范围内，至少提供一端）：

```json
{"stress": {"min": 0, "max": 100}}
```

**缺失标记**：默认只把实际空值和空白字符串视为缺失。特殊标记必须依照原始数据说明配置，
不能默认将样品名称 `NA` 当成缺失。IQR/MAD 的分组字段应按实验设计指定，避免混合不同材料。

## 示例工作流

`examples/clean.csv`、`examples/dirty.csv` 均为**人工构造的测试样例**，不是真实实验数据。
`dirty` 样例包括重复编号、缺失值、数值/日期格式错误和超范围值。
流程里的演示数据节点内嵌这些记录，不依赖本机绝对路径。

```powershell
.\.venv\Scripts\python.exe -m scripts.build_example
.\.venv\Scripts\python.exe -m scripts.run_example .\examples\clean_quality_flow.json --output .\artifacts\clean_report.json
.\.venv\Scripts\python.exe -m scripts.run_example .\examples\dirty_quality_flow.json --output .\artifacts\dirty_report.json
```

在 Langflow 的导入功能中选择 `examples/dirty_quality_flow.json` 或 `clean_quality_flow.json`。
流程有一个人工演示数据源、六个并行检查节点、一个汇总节点。运行汇总节点后查看报告/摘要。
换自己的数据时，将演示源替换为能输出原生 Table 的文件读取节点，并修改检查规则。

命令行示例会**重新导入导出的 JSON，再执行原生图**，不以直接调用 Python 检查函数代替流程测试。
`clean` 应完成六项且通过；`dirty` 应完成六项但发现问题。
参数错误会抛出明确错误，不会以空报告代替成功检查。

## 科学与接口边界

- 无行数据和无接入报告不能给出全部通过。
- 汇总只说明已接入的检查；未接入节点不在覆盖范围内。
- 问题明细可限制为 1–10000 条，但完整计数和最终结论不受预览截断影响。
- 行位置 `row_position` 从 0 开始；CSV 的物理行号还需考虑表头、多行单元格等。
- 重复记录可能是有效重复实验；异常值不自动删除或修正。
- MAD 为零时标记偏离重复中位数的值，并记录此回退；IQR/MAD 少于3个有效值时报告基线不足。
- 极大有限值使 IQR/MAD 中间计算溢出时，报告 NUMERICAL_LIMIT，不会给出通过。
  明确范围检查使用 Decimal 比较，保留超出浮点整数精度的输入差异。
  统计计算转换中出现不同精确值合并为同一浮点值、非零值下溢为零时，也停止该组的统计判定。
- 类型、单位、范围来自明确规则，不替代仪器校准、材料知识和研究者判断。
- 报告包含本地字段名、索引和检查依据；不要将其自动当作适合公开或发送云端的数据。

输出格式见 [docs/contract.md](docs/contract.md)。
`requirements.lock` 提供带平台标记的依赖固定清单。`requirements-tested-py310.txt`
记录本次 Windows/Python 3.10 实际验证环境，包含平台专用包，不应直接用于 Linux。
普通 wheel 安装后，可在组件包目录运行 `python -m scripts.verify_install --require-wheel`，
检查安装包中的七个节点是否被发现，并重新导入、执行两份流程。

## 目录

```text
components/materials_quality/  # Langflow 分类及七个原生节点
src/materials_quality/         # 可独立测试的检查算法和报告契约
tests/                        # 核心行为、原生加载和导出图执行测试
examples/                     # 人工CSV、演示源、可导入流程JSON
scripts/                      # 生成、重新导入和执行示例
docs/                         # 契约、设计和实现记录
```

参考：[Langflow 自定义组件规范](https://docs.langflow.org/components-custom-components)。
