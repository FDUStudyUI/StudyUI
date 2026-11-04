---
name: studyui-spectrum-analysis
description: 批量分析暗场或其他波长光谱，提取窗口候选峰、结构化特征和组内均值带。用于有曲线编号、波长和强度的长表；参数不完整时先补充信息。
compatibility: Python 3.10 and StudyUI scientific dependencies; no model or network required for execution.
metadata:
  version: 1.0.0
---

# 批量光谱分析

1. 检查 curve_id / x / y 与可选 group 映射。列名只提供建议，单位必须明确。每条曲线属于一个组。
2. 明确候选波长窗口，窗口按 nm 输入。λ₁₀ 表示低能耦合模式；本技能输出窗口候选，不完成物理模式确认。
3. 保留原始曲线；基线、平滑和峰检测调用现有 analyze_spectra。所有配置进入追溯。使用平滑时检查峰位和峰宽敏感性。
4. 输出所有峰的特征，同时保留逐曲线状态和候选。未检出记缺失，禁止填零；不能把峰数当成独立曲线数。
5. 分组描述统计和光谱带用于展示。曲线是否独立需要试验设计确认；技术重复的推断使用组间研究技能。
6. 从真实输出解释数量、有效候选、均值和失败原因，附图、表和追溯。IQR 是逐波长 25–75 百分位范围，不是置信区间。

工具：仅 `spectra` 固定任务。输入/输出约定见 [接口](references/contract.md)。
