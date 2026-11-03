# 批量工作流

先安装组件包并配置 Langflow 的组件目录，再从首页上传 JSON 工作流。

- `01_twenty_specimens.json`：内嵌 20 份完整合成拉伸试样，直接运行「批量·结果汇总」。
- `02_twenty_files_upload.json`：在「文件与样品入口」多选上传 `twenty_csv/` 中的 CSV，再运行汇总。

两条流程各 6 个节点。检查 → 力学分析 → 绘图对每份完整试样独立执行，输出每份样品的弹性模量、屈服强度、质量发现和状态。
合成真值为 `E = 200000 × (1 + i/10) MPa`，`i=0…19`；屈服结果由每条曲线与 0.2% 偏移直线的交点确定。
图件与 HTML 写入运行 Langflow 的电脑或服务器的临时目录。

重新生成：`python -m scripts.build_batch_examples`。详细操作见[批量分析指南](../../docs/batch-processing.md)。
