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
