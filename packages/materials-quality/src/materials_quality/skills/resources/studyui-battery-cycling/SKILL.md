---
name: studyui-battery-cycling
description: 处理电池充放电循环、容量衰减、倍率/温度对比和循环寿命数据；识别电芯、循环、步骤和时间序列层级，避免把测量点当独立样本。
metadata:
  version: "1.1.0"
  domain: "battery-cycling"
  triggers: "battery|batteries|cell cycling|cycle life|capacity fade|capacity retention|coulombic efficiency|state of health|SOH|电池|锂离子|循环寿命|循环容量|容量衰减|容量保持率|库仑效率|充放电|倍率|电芯|电化学循环|循环伏安|EIS"
---

# 电池循环与老化数据

1. 识别数据层级：电芯/样品、循环、充电/静置/放电步骤、单个采样点、参考性能测试。检查循环号是否重置、缺步、重复、截断，以及恒流/恒压/脉冲程序和终止阈值。
2. 从字段说明核对电流方向符号、时间单位、电压、电流、温度、容量和阻抗的含义。NASA Ames 公共数据把 cycle 下的 charge/discharge/impedance 操作及测量字段分层；`Capacity` 的试验定义和截止电压应随数据引用，不得把不同截止条件下容量直接当作同一测量。
3. 容量保持率必须声明参考基准（额定容量、首个合格循环或参考性能测试）、循环索引和公式；若数据未提供可比基准，只报告实测容量趋势，不擅自设置基准。区分 Ah、Wh、能量密度和功率，不由容量曲线推断安全性。
4. 库仑效率需在完整且可配对的充/放电循环上按确认的容量边界计算。部分循环、不同步的步骤、循环编号错位或容量数据质量不足时标注缺失，不用邻近循环补齐。
5. 区分独立电芯数和每个电芯内重复循环/每循环采样点。循环点是纵向重复测量；不能把数百个循环或数十万条时序行当作独立重复样本做组间显著性检验。
6. 只有相同测试协议、材料/电芯配置、温度、倍率、截止电压与容量定义可比时，才进行组间性能比较。偏离协议的条件要分层展示或列为混杂因素。
7. 保留原始时间顺序和每电芯身份；派生支路记录循环切分规则、容量积分方式、异常步骤排除依据和聚合层级。图表标明每条线对应电芯，不能只画组均值掩盖电芯差异。
8. 若工作流节点不支持电池循环解析，先查表格导入和可用时间序列/分组节点；不得编造专用电池节点或声称完成 SOC、SOH、EIS 等未实现模型。
9. 充电与放电字段分别筛选、分别检查缺失。若一行只包含其中一种步骤的数据，不得用“充、放电字段同时非空”的联合条件筛掉该行；分别输出有效数、缺失数和保留规则，原始导入表保持不变。
10. 需要描述统计时优先使用现有 `ScienceStatsGrouped`（目录项 `stats.grouped`）：它输出每个组和数值列的 n、均值、样本标准差、中位数、Q1、Q3、最小值和最大值。填写真实存在且非缺失的分组列与数值列；该节点允许单组描述，不必为了调用它而虚构分组。若按电芯/循环/步骤分组，先确认分组层级与研究问题一致，并保留每个电芯的身份。
11. `ScienceStatsDistribution`（`stats.distribution`）用于直方图、正态 Q-Q 图和 Shapiro 检验信息，不是描述统计表的替代品；长时间序列的采样点通常相关，不能把其 Shapiro p 值解释为电芯总体正态性，也不能据此进行独立样本推断。
12. 常用且经过核对的节点已知时，直接按目录名和真实输入列配置；不要为寻找同义功能反复搜索目录。若节点输入要求不明，再只查询该节点的必要字段，不要猜测端口或字段名。

## 参考

- [NASA Ames Li-ion Battery Aging 数据集说明](https://catalog.data.gov/dataset/li-ion-battery-aging-datasets)：循环结构、charge/discharge/impedance 字段和测试条件。
- [DOE/Sandia R&D Data Repository](https://www.sandia.gov/ess/tools-resources/rd-data-repository)：公开电池实验原始数据及相应论文记录。
- [K-Dense Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills)：仅借鉴科研 Skill 的触发/边界/输入输出组织方式，本文为 StudyUI 原创。
