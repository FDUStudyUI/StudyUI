---
name: studyui-units-and-uncertainty
description: 审核材料实验的物理量、单位换算、精度和测量不确定度；用于跨单位比较、派生量计算、校准/误差传播和量纲核查。
metadata:
  version: "1.0.0"
  domain: "metrology"
  triggers: "measurement uncertainty|uncertainty budget|calibration|unit conversion|dimensional analysis|standard deviation|standard error|置信区间|测量不确定度|不确定度|误差传播|校准|单位换算|量纲|有效数字|重复性|准确度|精密度"
---

# 单位与测量不确定度

1. 将每个量写成“数值 + 单位 + 定义 + 来源”。列名和数值量级不能单独确定单位；量纲不兼容的换算必须拒绝。
2. 区分标准差（样本离散）、标准误（估计精度）、置信区间（推断区间）、仪器分辨率和校准不确定度。未明确统计层级时不把某一个误差列自动解释为 SD/SEM/CI。
3. 简单确定性换算须保留换算因子和原始列。派生量 (y=f(x_1,…,x_n)) 的不确定度传播需要已知输入不确定度、协方差/独立性假设与模型；缺失时只能列出未量化的不确定度来源。
4. 校准信息与被测数据分开记录：仪器、标准物/参考材料、校准日期、适用量程、修正函数和校准不确定度。不要把制造商规格自动当成该次测量的不确定度。
5. 只有在独立实验单位明确时，才据此计算组间置信区间或标准误。技术重复可用于评估重复性，但不得冒充独立样本的推断不确定度。
6. 报告有效数字应与测量不确定度和方法精度匹配；转换单位不会增加精度。模型拟合参数的误差不是全部实验不确定度。
7. 核对已有节点是否执行了单位检查和误差传播；未执行的不能从图形误差带暗示其已被计入。

## 参考

- [K-Dense Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills)：公开目录含 Units and Measurement Uncertainty Skill，供覆盖范围参考；不复制其脚本或文本。
- [NIST DSC 参考物质](https://www.nist.gov/news-events/news/2025/01/rm-temperature-and-enthalpy-calibration-differential-scanning-calorimeters)：校准是非绝对热量测量的重要条件。
