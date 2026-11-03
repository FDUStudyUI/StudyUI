# 科研技能验收记录

版本：0.6.0。验收平台：Windows、Python 3.10、Langflow/LFX 1.13.0。

## 范围与证据

| 检查 | 结果 |
|---|---|
| 技能文件及普通 wheel | 安装包包含三个技能及参考资料，发现 62 个原生节点 |
| 科研技能专用测试 | 37 项通过，覆盖计划、科学任务、模型协议、CLI、原生接口及图连接 |
| 完整回归（包含启动器） | 784 项通过，10 项因本机缺少 HDF5/NetCDF/Zarr 可选依赖跳过，8 条依赖/统计样例警告 |
| 启动器最终修订 | 显式 UTF-8 旗标修订后 20 项启动器测试通过；支持中文目录，隔离 pip 配置，只读检查不安装 |
| 普通 wheel 的技能专用测试 | 37 项通过，测试进程从安装目标读取技能运行代码 |
| 原有五个质检流程 | 正常/修订数据 0 条发现，异常数据 8 条发现，追溯校验通过 |
| 真实浏览器验收 | 三类技能全部通过，页面错误和 HTTP 错误均为 0；三个 HTML 报告各有 1 张内嵌图，解码通过 |
| 大批量运行 | 1360 条合成光谱、545360 行、1360 行峰特征全部完成；两组各 680 条、候选均值均为 600 nm |
| 独立审查 | 已修复标识符类型推断、同义单位执行及框架输出缓存问题；补充对应回归 |

大批量案例在该次本机运行约 24.18 秒，包括分析、绘图和导出。该数值是给定合成数据的运行记录。
启动器在独立 Windows 服务完成真实启动、三流程预载、同名流程保留和 Ctrl+C 清理；复用环境未被安装或升级。
全新环境联网安装及 POSIX 包装器需在目标机器验收。合并前以最终提交的 CI、artifact 和测试日志复核。

本地 wheel SHA-256：`1bbafe4db00785bdc9f2f5fcc04348d44127bad850b66654c607e69b7bea3099`。重新构建或源码变更后需重新记录。

## 三条实际执行链

1. 光谱：数据源 → 任务规划 → 分析执行。8 条曲线、16 行峰特征，A/B 各 4 条候选，均值 715/755 nm。
2. 力学：20 份试样全部完成，首份弹性模量 200000 MPa、0.2% 偏移强度约 202.01005 MPa。
3. 组间研究：24 行技术测量聚合成 8 个试验单位，两组各 n=4，输出 Welch 检验、效应量与校正记录。

浏览器实际操作了窗口确认开关、待补计划、下限 650→720→650 nm 修改与恢复。
720 nm 时 A 组为 2 条候选、均值 725 nm；B 组仍为 4 条、均值 755 nm。未检出曲线保留缺失状态。
所有场景均通过画布按钮执行和输出查看器取回结果；报告在浏览器打开并检查图像。

## 校验边界

- 数据、单位或计划内容改变后，执行器拒绝旧计划。技能内容改变也会重新校验。
- 两个新组件关闭 LFX 的 `Output.value` 框架缓存，使用内部带输入/参数指纹的结果缓存；多输出复用一次计算。
- CLI 保留前导零和合法 `NA` 标识符，数值转换在分析副本中执行。
- 同义单位在规划检查等价后，仅对分析副本规范化，原始元数据保留。
- 模型协议通过本地 HTTP 模拟服务测试；未用该测试证明任何实际云模型的科研质量或费用。
- 模型非法 JSON、额外参数、超长响应、服务错误和未确认科学条件受到校验。请求不自动附加原始行。
- 所有示例均为合成数据，λ₁₀ 为窗口候选，图像与统计解释需遵循试验设计。

## 复跑

在组件包目录、已安装依赖的 Python 环境中：

```powershell
$env:PYTHONUTF8 = "1"
$env:MPLBACKEND = "Agg"
$env:OMP_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"
$env:OPENBLAS_NUM_THREADS = "1"
python -m pytest -q
ruff check src components tests scripts examples
python -m scripts.build_skill_examples
python -m build --wheel
```

真实界面需另启动独立 Langflow：

```powershell
python -m scripts.ui_skill_acceptance --base-url http://127.0.0.1:7867
```

Windows 可用 `--executable "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"` 指定已有浏览器。
测试通过真实选择/替换按键填写数值，并检查输入值，避免自动化的编辑缓冲把 `720` 与 `650` 拼接。

本地记录路径（运行产物不随源码提交）：

- `artifacts/skills-delivery-tests.log`
- `artifacts/skills-wheel-delivery-check.log`
- `artifacts/skills-wheel-delivery-tests.log`
- `artifacts/ui-skill-final-pass/acceptance.json` 及对应 JSON、画布与报告截图
- `artifacts/skills-stress-result.json`
- 仓库根目录 `artifacts/launcher-review/`：完整回归、启动器定向测试、只读检查、真实启动与退出记录

CI 会执行科研技能的单元/图连接测试与 `ui_skill_acceptance`，并上传运行记录。
