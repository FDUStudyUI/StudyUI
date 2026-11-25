---
name: studyui-experimental-design
description: 规划或检查材料科学实验的随机化、区组、因子设计、重复测量、批次和试验单位；适用于新实验设计与已有数据的设计审计。
metadata:
  version: "1.0.0"
  domain: "experimental-design"
  triggers: "design of experiments|DOE|factorial design|randomization|blocking|replication|repeated measures|experimental unit|pseudoreplication|正交试验|实验设计|试验设计|随机化|区组|因素设计|响应面|工艺优化|重复测量|实验单位|技术重复|生物重复|伪重复"
---

# 材料实验设计与设计审计

1. 明确研究问题、响应变量、处理因子/水平、控制条件、随机化单位和独立实验单位。样品、试件、批次、炉次、培养皿、电芯等层级不能互相替代。
2. 区分独立制备/独立批次（可能提供实验重复）、同一样品上的重复测量（纵向/配对）、同一试件的技术复测和同一试样上多点测量。采集点或仪器重复通常不能扩充独立样本量。
3. 检查处理与批次、日期、操作者、仪器、位置或材料批号是否混杂。存在已知系统差异时优先考虑区组/分层；无法拆分混杂时将其报告为识别限制。
4. 新实验先按目标选择设计：少数因素的筛选、析因/分数析因、响应面、配对/重复测量等。说明因子水平、随机化和重复策略；不要将“正交表”当作自动消除混杂或保证因果的证明。
5. 已收集数据时先复原原设计，记录每行观测所属的样品、独立批次、时间点和重复层级。无法恢复实验单位时只做描述性分析，不对伪独立行进行显著性推断。
6. 预先定义主要响应、比较范围、排除规则和多重比较范围。分析结果不理想时不能改试验单位或反复挑选显著模型。
7. 使用 StudyUI 已有 DOE 节点时核实随机种子、因子编码、中心点、重复、输出矩阵与用户方案一致；无对应能力时给出设计表草案或说明不支持，不虚称完成随机化。

## 参考

- [K-Dense Scientific Agent Skills：Experimental Design](https://github.com/K-Dense-AI/scientific-agent-skills)：借鉴设计、触发条件与分析边界的公开 Skill 组织形式；具体方法由 StudyUI 独立撰写。
- [ASTM C39/C39M](https://store.astm.org/c0039_c0039m-23.html)：例示试件制备、尺寸和养护条件对材料试验结果的影响。
