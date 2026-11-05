---
name: studyui-powder-xrd
description: 分析粉末 X 射线衍射测量表或衍射图谱，规划原始扫描导入、峰位/峰形描述、物相候选与 Rietveld 证据边界；适用于 XRD、PXRD、衍射和晶相分析任务。
metadata:
  version: "1.0.0"
  domain: "powder-x-ray-diffraction"
  triggers: "XRD|PXRD|powder diffraction|powder X-ray|x-ray diffraction|衍射|粉末衍射|衍射图谱|衍射峰|晶相|晶体结构|Rietveld|布拉格"
---

# 粉末 X 射线衍射

1. 首先区分探测器原始图像、仪器导出的扫描 profile、经积分/校正/归一化的数据和论文图中数字化曲线。横轴是 2θ、θ、d-spacing、q 还是 TOF 必须由文件/方法确认。
2. 导入时保留实测坐标和计数/强度；同时记录辐射源与波长、扫描几何、角度范围、步长、计数时间、样品旋转/环境、仪器和校准信息（若公开）。IUCr 的 `pd_meas` 区域定义测量数据及其条件；归一化、校正、平滑、零点修正等处理值应作为处理层另存。
3. 计数数据的散粒噪声与计数相关。不得对原始计数静默平滑、重分箱、背景扣除或归一化；处理副本需记录方法/参数，并保留与原测量的对应关系。
4. 峰位和相对峰强只能用于描述或生成候选。确认相组成需要可追溯的标准/数据库匹配、波长与仪器条件、峰重叠与择优取向检查。仅凭截图、文件名、一个峰或自动检索片段不得宣称确定物相。
5. 区分峰搜索、索引、结构求解、Rietveld 精修和定量相分析。若节点目录没有相应实现或没有晶体结构/仪器模型，不要把峰检测工作流叫作 Rietveld 或结构精修。
6. 若报告 Rietveld 拟合，应提供测量/计算/差值 profile 和可复核的数据/模型；不以单一 R 因子或拟合图作为结构正确的充分证据。
7. 明确对每个样品扫描进行了多少数据点、各扫描有效范围、峰检出/失败状态、背景处理、拟合区间和限制。没有元数据的单位/波长不得猜测。
8. 节点选择规则：先查 StudyUI 目录的 XRD 导入、衍射计算和可视化能力。只连接支持的节点；若只有表格统计和通用曲线图，就将流程命名为“衍射数据描述/可视化”，并说明不能完成相鉴定。

## 参考

- [IUCr Rietveld 指南](https://journals.iucr.org/b/services/powder.html)：应提供初级测量衍射数据；拟合图显示实验、计算与差值 profile。
- [IUCr Powder CIF `pd_meas`](https://www.iucr.org/__data/iucr/cifdic_html/1/cif_pd.dic/Cpd_meas.html)：区分未处理测量记录与处理后记录。
- [NIST：Poisson errors and adaptive rebinning](https://www.nist.gov/publications/poisson-errors-and-adaptive-rebinning-x-ray-powder-diffraction-data)：计数误差和分箱对衍射数据的影响。
