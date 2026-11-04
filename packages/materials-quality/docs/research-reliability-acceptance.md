# 科研可靠性 0.7.0 验收记录

本记录覆盖 V2 的正确性、独立评测与最小数据契约。实现沿用 62 个原生节点，普通操作使用列选择、下拉框、勾选和数值输入。使用方法见[科研可靠性说明](research-reliability.md)，可导入流程见[四个可靠性示例](../examples/reliability_flows/README.md)。

## 本地验证

环境为 Windows、Python 3.10.8、pandas 2.2.3、SciPy 1.15.3、Langflow/LFX 1.13.0。使用既有解释器，不更改其依赖；独立安装目标、浏览器和服务运行目录位于忽略的 `artifacts/` 中。

| 检查 | 结果 | 本地记录（相对组件包） |
|---|---|---|
| 完整回归 | 940 passed，10 skipped，8 warnings | `artifacts/v2-release-full.log` |
| 普通 wheel 安装后专项测试 | 117 passed，7 warnings | `artifacts/v2-release-wheel-tests.log` |
| 安装发现与旧质检流程 | 62 个组件；正常/修订为 0 条，异常为 8 条 | `artifacts/v2-release-wheel-check.log` |
| 原有三类科研任务真实界面 | 光谱、力学、组间研究均通过 | `artifacts/ui-skills-v2-release/acceptance.json` |
| 四个可靠性真实界面 | 竞争峰、嵌套样品、小样本、全部失败均通过 | `artifacts/ui-reliability-v2-release/acceptance.json` |
| Ruff、生成组件、差异格式、独立代码复核 | 通过；重要复核问题已补回归测试 | 测试源码及 PR 检查 |

10 项跳过涉及当前 Windows 环境未安装的可选 HDF5、NetCDF、Zarr 依赖。CI 安装独立环境并运行完整回归。警告包括依赖弃用和恒定统计量的数值精度提示；跳过和警告均不计为已验证能力。

真实界面验证覆盖上游连线、计划与执行、原生候选规则切换、噪声模式切换、保存后重新打开、报告与内嵌图片。两份记录的页面和 HTTP 错误均为 0；四个新流程未输入 JSON，包含 9 次参数持久化读回。保存使用 Langflow 原生 Ctrl+S，随后只读检查保存结果；未通过接口直接写入参数。

竞争峰示例分别选出 730/790 nm；嵌套示例保留 12 条曲线、6 个独立样品，以每组 3 个样品比较；每组 2 个单位默认仅描述；全部失败示例保留失败分母和失败报告。

## 安装包

文件：`langflow_materials_quality-0.7.0-py3-none-any.whl`。

SHA-256：`2ffbcc32ec4faaa8a7c5c0e9f6c5f2bacc05305080af0a5690df7a5696143320`。

142 个打包代码、组件和资源文件与构建时源码逐字节一致。安装包专项测试导入独立安装目标中的代码；原有环境不作安装或升级。源码及可复现构建方式随仓库交付，wheel 由 GitHub Actions 上传为构建产物。

## 独立评测与提交绑定

光谱评测包含 260 个冻结解析任务、280 条曲线，六种策略/规则组合；统计设计包含 512 次独立模拟试验和独立闭式参照。逐项结果、失败、分母、种子、环境与源码哈希均保存。方法、历史结果及重跑命令见[独立评测](evaluation-reliability.md)。

最终提交的 CI 自动执行两类评测、完整回归、wheel 安装与真实浏览器流程，并上传记录。具体提交 SHA、CI 链接及结论以 [PR #6](https://github.com/FDUStudyUI/StudyUI/pull/6) 的最终说明和该提交检查为准；历史运行不替代当前提交验证。

本次没有完成自主修订闭环或真实论文数据的逐峰外部验证。解析真值测试与重复模拟证明所列条件下的数值和设计行为，不构成真实仪器数据的总体准确率。
