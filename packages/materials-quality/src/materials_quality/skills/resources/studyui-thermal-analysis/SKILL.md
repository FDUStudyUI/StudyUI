---
name: studyui-thermal-analysis
description: 审查 DSC、TGA/TG、DTA 和其他材料热分析曲线，区分测量量与派生事件，检查气氛、程序、升温速率和校准证据。
metadata:
  version: "1.0.0"
  domain: "thermal-analysis"
  triggers: "DSC|TGA|TG|DTA|STA|thermogravimetry|differential scanning calorimetry|thermal analysis|calorimetry|热重|差示扫描量热|差热分析|热分析|玻璃化转变|熔融峰|结晶峰|失重曲线|热流"
---

# 材料热分析数据

1. 按 IUPAC 术语识别曲线的被测量：DSC 为样品与参比间热流率差，TG/TGA 为质量随温度/时间变化，DTA 为温差。不能因为列名包含 temperature 或 heat 就断定测量技术。
2. 记录温度/时间、热流/质量、单位、升温/降温/等温程序、升温速率、气氛/流量、坩埚、样品质量、空白/基线和仪器校准信息；数据说明未提供的内容明确标未知。
3. 区分实测曲线与基线校正、质量归一化、导数曲线、峰分解和积分焓。所有派生支路写明算法、区间、基线和归一化质量；不修改源曲线。
4. 事件温度必须定义是 onset、峰顶、终点还是人为阈值。放热/吸热方向受仪器约定影响，先核对导出说明；不可仅凭峰向判断放/吸热。
5. 不把单条 DSC/TG 曲线等同于重复实验。若有多次重复，先分清独立样品、同一样品重复扫描和仪器重复；组间推断按实验设计处理。
6. DSC 不是绝对测量；NIST 强调温度、焓和热容测量需要校准。扫描速率、样品质量、热滞后、气氛和坩埚可改变峰位/形状；跨组比较须确认协议一致或将差异纳入解释。
7. 仅当仪器、标准物和扫描条件支持时报告温度/焓。材料转变归属需要相组成、热历史和独立证据；单峰不唯一指向某个化学/晶体事件。
8. 检查节点目录是否有对应热分析计算能力。只有通用曲线导入/作图时可做数据质量检查和可视化，不声称自动完成热焓、动力学或相变定量。

## 参考

- [IUPAC Gold Book：thermal analysis](https://goldbook.iupac.org/terms/view/T06295)：受控温度程序下测量物性随温度变化的技术总称。
- [NIST：DSC 校准参考物质](https://www.nist.gov/news-events/news/2025/01/rm-temperature-and-enthalpy-calibration-differential-scanning-calorimeters)：DSC 非绝对测量及温度/焓校准需求。
- [NIST DSC/DTA recommended practice](https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication960-15.pdf)：校准、气氛、坩埚、程序与样品条件。
- [NIST DSC measurement and analysis guidance](https://www.nist.gov/publications/measurement-and-analysis-results-obtained-biological-substances-differential-scanning)：扫描速率依赖、测量与校准考量。
