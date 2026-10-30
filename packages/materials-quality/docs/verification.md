# 验证记录（2026-10-30）

## 实际运行环境

Windows，Python 3.10.8，LFX 1.13.0，pandas 2.3.3，Pint 0.24.4。
平台标记依赖固定在 requirements.lock；Windows 实际安装清单另存于 requirements-tested-py310.txt。

## 已执行

- 完整 pytest：**92 passed**。
- Ruff：**All checks passed**。
- 真实 Langflow 自定义代码加载器接受七个组件；目录发现列出全部七个组件。
- 两份示例均通过原生 Graph 序列化、重新导入与实际执行。
- 干净样例：完成6项检查、0条发现、passed=true。
- 脏数据样例：完成6项检查、8条发现、5项需复核、passed=false。
- wheel 构建成功，在另一个虚拟环境普通安装后发现七个节点，并执行两份导出图。
- wheel 中7个核心 Python 文件与待提交源码逐文件 SHA256 相同。
- 团队目录 packages/materials-quality 中再次执行完整测试和 wheel 流程，结果一致。

## 独立复核与回归

独立代码复核发现的统计溢出、精确范围比较舍入、汇总报告内部矛盾均先通过失败用例复现，
再修复。追加复现并修复了浮点转换碰撞/下溢、CSV数值缺失标记和跨字段别名复用。
复核没有遗留的可选小项。报告生成、检查执行和预览截断均不依赖模型计算。

## 验证边界

- 测试输出有4条来自上游 LFX/Pydantic 的弃用警告，不是测试失败。
- 示例数据为人工测试样例，不代表任何材料实验或真实设备诊断结果。
- 已验证组件加载与图执行；**尚未进行浏览器画布的视觉检查**。
- GitHub Actions 的 Linux 结果以仓库 Actions 页面为准，不以本地 Windows 结果代替。
- 团队实际部署版本尚待确认；当前不声明其他 Langflow/LFX 版本已通过测试。
