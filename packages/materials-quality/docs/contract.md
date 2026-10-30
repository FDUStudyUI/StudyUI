# 检查报告契约 v1.0

## 类型

检查输入为 pandas/Langflow DataFrame。组件输出分别是原生 DataFrame（数据/问题表）
以及 Data（报告）；汇总摘要为 Message。参数不合法抛出 ValueError，质量问题通过报告表达。

## 报告字段

| 字段 | 含义 |
|---|---|
| schema_version | 固定 `1.0` |
| check_id | schema/missing/types/units/duplicates/outliers/aggregate |
| execution_status | 已完成检查为 completed；未接入报告的汇总为 insufficient |
| passed | 在配置覆盖范围内，未发现 warning/error 才为 true |
| dataset | 输入行数、列数；汇总另保留各项检查的原始报告 |
| parameters | 本次明确使用的检查规则 |
| metrics | 各检查指标；汇总为完成数、通过数、有问题检查数 |
| total_findings | 截断之前的完整发现数 |
| returned_findings | 当前报告所含明细数 |
| truncated | 是否省略了部分明细 |
| findings | 有界的问题明细 |
| checks | 仅汇总报告：原始检查报告列表 |

## 问题明细

`check_id`, `code`, `severity`, `column`, `row_position`, `row_index`, `reason`。
`row_position` 为零基位置，唯一定位本次表格中的行；`row_index` 保留索引标签，可能重复。
列级或表级发现的行字段为 null。问题代码稳定，reason 是给人阅读的说明，不应作为机器判断键。
findings表即使为空，也保留固定列。

常见代码：MISSING_COLUMN、AMBIGUOUS_COLUMN、MISSING_VALUE、TYPE_OR_FORMAT、
UNIT_INCOMPATIBLE、UNIT_MIXED、UNIT_UNSPECIFIED、UNIT_UNKNOWN、UNIT_VALUE_FORMAT、
DUPLICATE_RECORD、OUTLIER_RANGE、OUTLIER_IQR、OUTLIER_MAD、NON_NUMERIC、NON_FINITE、
INSUFFICIENT_BASELINE、NUMERICAL_LIMIT、EMPTY_TABLE、EMPTY_SCHEMA。

当前六项检查仅发出 warning/error 发现。汇总器校验完整字段、非负整型维度/计数、
明细数、截断标记及 passed 一致性；不接受缺字段或内部矛盾的报告。
明确范围阈值可用精确十进制字符串表达，报告保留其精度。

报告可以用 `json.dumps(report, allow_nan=False)` 序列化。
数值运算不由语言模型执行；当前这批节点不调用网络。
# 共享规则与追溯扩展（0.2）

报告保留 schema_version=1.0 基础字段，新增可选 provenance；原有纯函数 API 保持不变。
Native Component 自动通过 run_check 添加追溯。共享上下文格式为 materials-quality-context/1，见 context.py。

共享规则对象只有 missing_tokens、group_by、checks 三个顶层字段。checks 使用 schema/missing/types/units/duplicates/outliers 标识和对应纯函数关键字；检查级不得重复指定 missing_tokens、group_by、finding_limit。问题明细上限由节点设置。

已连接共享规则时，独立节点配置不参与执行。类型/单位/异常检查新增可选 missing_tokens 参数；共享策略通过此参数显式传递，不做值替换，避免空字符串语义冲突或大整数因空值变为浮点数。分组字段、重复判定键和传递的表格不变。未传 missing_tokens 保留原 API 默认行为。

dataset.fingerprint 是 materials-table/1 流式 SHA-256，包含列名、dtype、索引名、逐行索引和带类型的单元格。provenance 记录模式、数据指纹、source 声明、共享规则快照/摘要和实际参数摘要。哈希不是来源真实性证明。

汇总对 traced 报告校验数据集、来源、规则、模式和唯一检查标识；拒绝 traced/legacy 混合。全 legacy 汇总仍可使用，但 provenance_status=unverified_legacy。汇总的 verified 只表示追溯一致性通过。单份检查的 passed 只针对其检查范围，未执行的检查没有结论。

