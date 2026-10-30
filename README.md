# StudyUI

基于 Langflow 的可视化科研 Agent 工作流。

材料数据质量检查组件包包含六个检查节点（结构、缺失、类型格式、单位、
重复记录、异常值）、共享规则与追溯节点、报告汇总节点，以及测试、依赖固定清单和可导入示例。
检查不修改原数据，不需要大模型 API Key。

[材料力学测试案例](packages/materials-quality/examples/mechanics/README.md)提供正常、问题、
人工修订后三份模拟教学数据和工作流，展示分组检查、合理重复测量、来源与规则追溯。

完整说明：[packages/materials-quality/README.md](packages/materials-quality/README.md)。

## 开始使用

```powershell
cd packages/materials-quality
$env:PYTHONUTF8 = "1"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[langflow,dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

网页编辑器接入方式及示例工作流见组件包说明。当前验证目标是 LFX 1.13.0 / Python 3.10；
团队运行版本尚未最终确认。已完成 [Langflow 1.13.0 真实画布验收](packages/materials-quality/docs/ui-acceptance.md)，
并提供运行时测试、wheel 安装验证和独立 UI 自动验收脚本。

## 目录约定

```text
packages/materials-quality/    # 独立组件包
.github/workflows/             # CI
```

后续前端、Agent 编排和其他专业分析模块可在独立目录增加；本次不包含这些模块。
