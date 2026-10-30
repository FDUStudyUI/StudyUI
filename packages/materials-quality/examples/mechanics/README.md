# 材料力学测试数据质量检查案例（模拟教学数据）

## 场景与边界

同一种材料的三个模拟样品批次 A/B/C，各在 ambient（25 ℃）和 hot（80 ℃）工况下，使用两个独立试样进行拉伸测试。`sample_id` 是样品批次，`replicate` 是该批次、该工况下的独立试样编号；不是将同一已断裂试样重复拉伸。`stress` 表示测试结果表中的强度值，声明单位 MPa。本案例只验证结果表的数据质量，不计算弹性模量、屈服强度或材料性能结论。

数值为人工构造，没有真实实验来源，IQR 倍数只是教学设置，不代表材料试验标准。分组以 condition 为准；它是实验记录的独立工况字段，温度列错误不会把该行悄悄改分到其他工况。

## 文件与演示顺序

1. `clean.csv` / `clean_flow.json`：12 行，六项检查无发现。组合键 sample_id + condition + replicate 唯一；单看 sample_id 会误把合理重复当重复记录。
2. `dirty.csv` / `dirty_flow.json`：8 条发现，涉及 6 行；见下表。导入后点击汇总节点运行按钮，查看“汇总报告”和“汇总问题明细”。
3. `manual_corrections.json`：案例作者对照预先定义的模拟真值逐项手工修订，记录位置、原值、新值、理由和文件摘要。此步骤不能解释为能自动恢复真实缺失数据。
4. `corrected.csv` / `corrected_flow.json`：修订后的独立副本，原 dirty.csv 不覆盖；复核后六项检查无发现。

| 零基行位置 / CSV 行号 | 人工注入的问题 | 应有发现 |
|---|---|---|
| 2 / 4 | stress 为缺失标记 -200 | missing/MISSING_VALUE；不进入类型、单位和离群基线 |
| 5 / 7 | stress 从 310 变为 900 | outliers/OUTLIER_IQR；仅标记复核，不删除 |
| 6 / 8 | temperature 写成 80 MPa | types/TYPE_OR_FORMAT；units/UNIT_INCOMPATIBLE；该列 UNIT_MIXED |
| 9 / 11 | date 使用 30/10/2026 | types/TYPE_OR_FORMAT |
| 10、11 / 12、13 | 最后一行独立试样编号错录为 1 | duplicates/DUPLICATE_RECORD 两条，标记组合键的两个成员 |

温度字段写成压力单位，既是量纲不兼容，也是同列单位混杂，两个发现有不同含义。`expected_findings.json` 是人工给定的独立预期，不由检查器的输出生成。

dirty 的 ambient 强度有效基线为 `[300,302,306,308,900]`，排除了 -200。Q1=302、Q3=308、IQR=6，1.5 倍围栏为 [293,317]，因此标记第 5 行。hot 分组独立建立基线，避免将温度条件带来的组间差异混入异常判断。以上不证明 900 在真实实验中一定错误。

## 运行与追溯

在包根目录执行：

```powershell
$env:PYTHONUTF8 = '1'
python -m scripts.build_mechanics
python -m scripts.run_example examples/mechanics/dirty_flow.json --output artifacts/mechanics_dirty.json
python -m scripts.run_example examples/mechanics/corrected_flow.json --output artifacts/mechanics_corrected.json
```

每份流程内嵌记录、规则和组件代码，可直接导入，无 API Key 或本机绝对路径依赖。来源记录保留 CSV 字节 SHA-256；共享上下文另计算内存表格指纹，包含值、类型、列序、行序和索引。原文件摘要是来源声明，不是签名；内嵌数据和 CSV 转换后的表格由生成脚本对应。

完整报告包含规则集名称/版本/摘要、实际检查参数、原始行索引和分组阈值。修改数据或规则后需重新生成上下文；不同数据、来源或共享规则版本的报告不能混合汇总。`clean.csv` 与 `corrected.csv` 可有相同内容摘要，但来源名称和数据集编号不同，仍不能混合。
