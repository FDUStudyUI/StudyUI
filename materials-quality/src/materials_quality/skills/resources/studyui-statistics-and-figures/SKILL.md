---
name: studyui-statistics-and-figures
description: 对具有明确独立试验单位和技术样本的长表开展组间研究，输出描述统计、总体检验、两两比较、效应量、Holm/FDR 校正与可追溯图表。
compatibility: Python 3.10 and StudyUI scientific dependencies; no model or network required for execution.
metadata:
  version: 1.1.0
  domain: experimental-statistics
  triggers: "group comparison|statistical test|ANOVA|Welch|Mann-Whitney|Kruskal|effect size|multiple comparisons|confidence interval|box plot|scatter plot|组间比较|显著性检验|方差分析|效应量|多重比较|置信区间|箱线图|误差棒|统计分析"
---

# 组间研究与绘图

1. 首先选择描述性汇总还是统计推断。明确 group、variable、value、sample_id、experimental_unit 和测量值单位。样本编号不能自动等同于独立试验单位。
2. 用户声明 independent 或 paired；配对设计要求单位完整匹配。先按独立试验单位平均技术重复。
3. 预先选择参数或非参数策略；参数法采用 Welch/配对 t 等已有实现，非参数法使用 Mann–Whitney/Kruskal/Wilcoxon。
4. 多重比较明确使用 Holm 或 FDR，报告校正族范围。禁止反复切换检验以追求显著。
5. 记录各组独立单位数、效应量、原始与校正 p 值。退化数据或不足样本显示不可估计及原因。
6. 小样本先展示原始独立单位数据和组内分布；图中的每个点须说明代表独立实验单位、样品均值还是技术重复。
7. 绘图展示独立单位均值及分组分布，保留单位、变量、缺失/剔除数量和分析依据。显著性不等于实际重要性或因果性；解释受试验设计和数据范围约束。

工具：仅 `contrast` 固定任务。接口见 [接口](references/contract.md)。
