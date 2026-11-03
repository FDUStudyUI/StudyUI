---
name: studyui-statistics-and-figures
description: 对具有明确独立试验单位和技术样本的长表开展组间研究，输出描述统计、总体检验、两两比较、效应量、Holm/FDR 校正与可追溯图表。
compatibility: Python 3.10 and StudyUI scientific dependencies; no model or network required for execution.
metadata:
  version: 1.0.0
---

# 组间研究与绘图

1. 明确 group、variable、value、sample_id、experimental_unit 和测量值单位。样本编号不能自动等同于独立试验单位。
2. 用户声明 independent 或 paired；配对设计要求单位完整匹配。先按独立试验单位平均技术重复。
3. 预先选择参数或非参数策略；参数法采用 Welch/配对 t 等已有实现，非参数法使用 Mann–Whitney/Kruskal/Wilcoxon。
4. 多重比较明确使用 Holm 或 FDR，报告校正族范围。禁止反复切换检验以追求显著。
5. 记录各组独立单位数、效应量、原始与校正 p 值。退化数据或不足样本显示不可估计及原因。
6. 绘图展示独立单位均值及分组分布，保留单位、变量和分析依据。解释受试验设计和数据范围约束。

工具：仅 `contrast` 固定任务。接口见 [接口](references/contract.md)。
