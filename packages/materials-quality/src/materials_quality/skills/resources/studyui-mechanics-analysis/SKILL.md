---
name: studyui-mechanics-analysis
description: 对单样品或批量单调拉伸应力应变数据计算弹性模量、偏移法规定塑性延伸强度和最大工程应力，并输出完整曲线、失败状态及报告。
compatibility: Python 3.10 and StudyUI scientific dependencies; no model or network required for execution.
metadata:
  version: 1.0.0
---

# 材料力学分析

1. 确认数据是工程应力应变；输入已经完成力与尺寸到应力、位移与标距到应变的换算。
2. 映射 strain、stress、sample_id；无编号时必须明确 single_sample。声明 strain_unit 和 stress_unit。
3. 用户指定弹性拟合区间 fit_range（单位与输入应变一致），检查至少三个点和拟合质量。禁止为了得到预期模量自动挑选区间。
4. 逐样品调用现有 mechanics；yield_offset 按应变分数填写，默认 0.002。结果名称为偏移法规定塑性延伸强度。
5. 缺少偏移线交点时保留缺失；最后测量点不自动认定为断裂。逐样品保留警告和失败状态。
6. 输出样品指标、完整应力应变及拟合/偏移线，解释 MPa 与 GPa 的关系，附来源和参数。

工具：仅 `mechanics` 固定任务。接口见 [接口](references/contract.md)。
