# 验证记录（2026-10-30，0.2.0）

> 这是首批质检节点的历史验证记录。完整 50 项功能的最新验收见 [全套记录](full-suite-acceptance.md)。

## 实际运行环境

Windows，Python 3.10.8，LFX 1.13.0，pandas 2.3.3，Pint 0.24.4。
平台标记依赖固定在 requirements.lock；Windows 实际安装清单另存于 requirements-tested-py310.txt。
真实界面环境另验证 langflow-base 1.13.0 / LFX 1.13.0 / pandas 2.2.3 / Chrome 156.0.8078.48；完整 Windows UI 快照在 requirements-ui-tested-py310.txt，勿作为 Linux 安装清单。

## 已执行

- 原运行时及真实 UI 环境完整 pytest 均为 **131 passed**。
- Ruff：**All checks passed**。
- 真实 Langflow 自定义代码加载器接受八个组件；独立 wheel 安装后的目录发现列出全部八个组件。
- 两份示例均通过原生 Graph 序列化、重新导入与实际执行。
- 干净样例：完成6项检查、0条发现、passed=true。
- 脏数据样例：完成6项检查、8条发现、5项需复核、passed=false。
- wheel 构建成功，在另一个虚拟环境普通安装后发现八个节点，并执行五份导出图。
- wheel 中17个核心及组件 Python 文件与待提交源码逐文件 SHA256 相同。
- 团队目录 packages/materials-quality 中再次执行完整测试和 wheel 流程，结果一致。
- 材料力学 clean/dirty/corrected 为 0/8/0 条发现；每份完成六项检查。
- 真实 Chrome 执行文件导入、9节点19连线检查、输出查看/复制、明细和中文摘要、无效规则阻断与恢复，见 [界面验收记录](ui-acceptance.md)。

## 独立复核与回归

独立代码复核发现的统计溢出、精确范围比较舍入、汇总报告内部矛盾均先通过失败用例复现，
再修复。追加复现并修复了浮点转换碰撞/下溢、CSV数值缺失标记和跨字段别名复用。
复核没有遗留的可选小项。报告生成、检查执行和预览截断均不依赖模型计算。

本轮独立复核的四项 Important 问题均先复现再修复：NumPy 时间值与整数的指纹碰撞、全列异常检查漏用缺失标记、显式空缺失标记列表不生效、timedelta 列兼容性。没有遗留 Critical/Important 或单独提出的 Minor 项。共享缺失策略现在以显式可选参数传入原纯检查函数，不替换或转换数据；未传新参数时保留原 API 默认行为。

## 验证边界

- 原运行时有4条、真实 UI 环境有7条上游弃用警告，不是测试失败。
- 示例数据为人工测试样例，不代表任何材料实验或真实设备诊断结果。
- 浏览器画布视觉及交互验收已通过，证据位于 docs/ui-evidence/。数据为模拟教学数据，人工修订依据预先定义的模拟真值，不代表可自动恢复真实实验数据。
- GitHub Actions 的 Linux 结果以仓库 Actions 页面为准，不以本地 Windows 结果代替。
- 团队实际部署版本尚待确认；当前不声明其他 Langflow/LFX 版本已通过测试。

补充跨平台交付回归：模拟 Git LF 检出验证三份 CSV 摘要；生成的 JSON 使用固定 LF，避免 Windows 换行转换使证据摘要失效。三项回归先失败后通过。
