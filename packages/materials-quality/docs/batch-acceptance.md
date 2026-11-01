# 0.5.0 批量科研任务验收

验证环境：Windows、Python 3.10.8、Langflow / LFX 1.13.0。所有案例使用仓库代码和声明的依赖，不依赖个人 skill 文件。

## 验证范围

| 检查 | 结果 |
|---|---|
| 完整 pytest 套件 | 738 passed；8 条依赖弃用或退化统计样例警告 |
| Ruff 与差异空白检查 | 通过 |
| 普通 wheel 安装 | 60 个组件被发现；原有五份质检流程通过，问题版保留 8 条发现 |
| 20 份完整拉伸曲线 | 每份独立计算；E 与单份计算一致；一项失败不隐藏其他样品 |
| 1360 条光谱压力测试 | 545360 行完整测量点；逐曲线特征、状态和分组汇总 |
| 真实浏览器：分组表格与 20 文件上传 | 两条流程各 6 个节点、5 条连线；各 20 项完成，逐项核对 E |
| 真实浏览器：光谱特征连接统计 | 8 条曲线、16 行峰特征、8 行窗口候选；两组各 4 条，均值 715/755 nm |
| 真实浏览器：光谱 IQR 带 | 每组 4 条完整曲线；真实填充带及独立 HTML 图片可读 |
| 迁移 | 已知配置转换为原生控件；自定义、未知或有歧义配置保留原 JSON 和原因 |
| 数组接入 | 合成 HDF5、NetCDF、Zarr 2 的实际解码、轴选择、元数据、边界及无效通道测试 |

浏览器操作通过导入、文件管理器、表单、运行及输出查看完成；未用后台接口代替导入或执行。目录统计与请求形状由被动观察核对。
1360 条是运行时压力测试，不代表在浏览器中验收了 1360 条实验光谱。

## 回归问题

已覆盖并修复：分组后陈旧单位字典、原生表输出丢失 attrs、自定义列选项丢失、重复上传回调、
缺失图像与逐图标尺错误的隔离、生成图像被修改后的重建、汇总指标覆盖状态与身份、历史指标遮蔽最新指标、
百分比等有缩放无量纲量的对数计算，以及 Zarr 内容变更、遍历限额和哈希读取失败。

时间验证按未来留出或过去训练的块验证执行，重复实验单位跨边界时拒绝；组间推断先聚合技术重复。
普通随机拆分及原有单样品算法保留。λ₁₀ 仅按显式窗口与候选规则提取，不声称自动确认物理模式或复现论文未公开的拟合方法。

## 复跑

```powershell
python -m pytest -q
ruff check src components tests scripts examples
python -m scripts.build_science_examples --verify
python -m scripts.build_batch_examples
python -m scripts.build_research_examples
python -m build --wheel
python -m scripts.verify_install --require-wheel
```

`verify_install --require-wheel` 应在安装普通 wheel 的独立环境执行。浏览器验收另在独立、已重启的 Langflow 服务执行：

```powershell
python -m scripts.ui_batch_acceptance --base-url http://127.0.0.1:7867
python -m scripts.ui_research_acceptance --base-url http://127.0.0.1:7867
```

本地使用 Edge 时可传入对应脚本的 `--executable` / `--chrome-executable` 参数；CI 安装 Playwright Chromium。
Windows 临时目录权限受限时，pytest 可指定 `--basetemp=artifacts/pytest-local`。

## 界限

示例均为合成数据。未宣称复现所引论文的完整实验；原始论文数据未随组件包提交。
Zarr 3 数据读取未在 Python 3.10 环境验证；当前测试使用 Zarr 2。
完整自定义树控件、画布子流程折叠、跨画布实时 schema 订阅和编辑器级即时错误标记，需要另行修改 Langflow 编辑器。
组件升级后应重启服务，避免旧目录缓存把新版多文件端口按旧定义校验。
