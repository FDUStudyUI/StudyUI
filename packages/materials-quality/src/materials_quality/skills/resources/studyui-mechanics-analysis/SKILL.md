---
name: studyui-mechanics-analysis
description: 对单样品或批量单调拉伸应力应变数据计算弹性模量、偏移法规定塑性延伸强度和最大工程应力，并输出完整曲线、失败状态及报告。
compatibility: Python 3.10 and StudyUI scientific dependencies; no model or network required for execution.
metadata:
  version: 1.2.0
  domain: mechanical-testing
  triggers: "tensile data|tensile test data|tensile stress-strain|stress-strain data|stress-strain curve|stress strain|elastic modulus|Young modulus|yield strength|ultimate tensile strength|engineering stress strain|拉伸数据|拉伸曲线|拉伸应力应变|应力应变|弹性模量|杨氏模量|屈服强度|抗拉强度|应变硬化"
---

# 材料力学分析

1. 确认数据是工程应力应变；输入已经完成力与尺寸到应力、位移与标距到应变的换算。若是载荷–位移、真应力应变或压缩试验，不能直接套用本拉伸指标流程。
2. 映射 strain、stress、sample_id；无编号时必须明确 single_sample。声明 strain_unit 和 stress_unit。
3. 用户指定弹性拟合区间 fit_range（单位与输入应变一致），检查至少三个点和拟合质量。禁止为了得到预期模量自动挑选区间。
4. 逐样品调用现有 mechanics；yield_offset 按应变分数填写，默认 0.002。结果名称为偏移法规定塑性延伸强度。
5. 缺少偏移线交点时保留缺失；最后测量点不自动认定为断裂。逐样品保留警告和失败状态。
6. 不从应力应变列推断缺失的标准、试样方向、标距或试验速度；不同几何、速率、温度和材料状态未核实前不跨组比较。
7. 输出样品指标、完整应力应变及拟合/偏移线，解释 MPa 与 GPa 的关系，附来源和参数、逐样品覆盖及失败状态。

工具：仅 `mechanics` 固定任务。接口见 [接口](references/contract.md)。
