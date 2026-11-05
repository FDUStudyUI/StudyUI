---
name: studyui-spectrum-analysis
description: 批量分析暗场或其他波长光谱，提取窗口候选峰、结构化特征和组内均值带。用于有曲线编号、波长和强度的长表；参数不完整时先补充信息。
compatibility: Python 3.10 and StudyUI scientific dependencies; no model or network required for execution.
metadata:
  version: 1.1.0
  domain: optical-spectroscopy
  triggers: "photoluminescence|PL|fluorescence|Raman|UV-Vis|UV Vis|absorbance|emission spectrum|wavelength spectrum|dark-field|dark field|plasmonic|plasmon|光致发光|PL光谱|荧光|拉曼|紫外可见|吸收光谱|发射光谱|暗场光谱|等离激元|纳米间隙|单染料|光谱峰|光谱曲线"
---

# 批量光谱分析

1. 先辨别光谱技术和导出量：波长/波数/能量、强度/吸光度/计数、采集模式、激发波长、仪器校正和单位。确认列映射和曲线/样品身份；列名只提供建议。
2. 该节点接口以波长 nm 为横坐标。只有来源能支持 nm 时才执行；若输入为波数、eV、像素或波长未知，需经节点支持的转换/校准证据处理，否则先做文件审查，不猜单位。
3. 明确候选波长窗口，窗口按 nm 输入。λ₁₀ 表示低能耦合模式；本技能输出窗口候选，不完成物理模式确认。峰位置不能单独识别材料态、分子机制或发光增强因果。
4. 保留源曲线；基线、平滑、归一化和峰检测在派生支路调用现有 analyze_spectra。所有配置进入追溯。平滑/基线方法需检查峰位、峰高和峰宽敏感性。
   在选绘图或曲线算法前先检查横坐标是否唯一且严格递增。若波长/波数坐标重复或顺序不单调，不要把它送入要求唯一递增坐标的曲线节点，也不要靠重试、去重、重采样或排序静默修复原始数据。保留原始表；改用能保留每个观测点的散点/点图与适用的描述性分组统计。只有用户明确授权并有可追溯的方法时，才建立另一个派生支路进行坐标整理，并记录方法及前后行数。
5. 输出所有峰的特征、逐曲线处理状态、覆盖窗口和失败原因。未检出保留缺失，禁止填零；不能把峰数、每个波长点或重复扫描当成独立样本。
6. 分组描述统计和光谱带主要用于展示。独立样品数与技术重复需按实验设计确认；技术重复的推断使用组间研究技能。IQR 是逐波长 25–75 百分位范围，不是置信区间。
7. 说明数据层级（仪器 raw / 导出 / 作者 Source Data）、基线/平滑/归一化状态和源 SHA；报告实际处理的曲线数与未覆盖曲线。

工具：仅 `spectra` 固定任务。输入/输出约定见 [接口](references/contract.md)。
