# 领域开发验证归档

以下段落从领域手册移入，保留原始数值和执行表述，反映对应开发阶段；不作为当前版本的重新验收。
当前操作入口见[文档索引](../README.md)。

## science-statistics.md

### Executed evidence

Review-cycle final command: `python -m pytest tests/test_science_stats.py tests/test_science_viz.py --basetemp artifacts/pytest-stats-review-final -q`, with `PYTHONUTF8=1`, `MPLBACKEND=Agg` and `OMP_NUM_THREADS=MKL_NUM_THREADS=OPENBLAS_NUM_THREADS=1`: **70 passed in 12.21 s**. The preceding RED run reproduced nine failures (61 passed) across manifest dispatch, Excel text typing, CSV schema preservation and mechanics ordering/resampling. All owned modules, tests and example scripts pass Ruff. `examples/science/statistics/run_demo.py` completed and wrote `artifacts/science-statistics-review-demo/statistics-demo.json` with 30 operation runs. It includes all eight descriptors, histogram/Q-Q/Shapiro, three correlations, six significance methods, four comparison/correction methods, seven model families, reloaded prediction, config/upstream manifest-only prediction/evaluation, holdout/CV and explicit-vector evaluation. Model files are reloaded and their predictions checked inside every fitted-model run.


## science-visualization.md

### Executed evidence

Review-cycle final domain tests: **70 passed in 12.21 s**, including all numerical plot/roundtrip/security assertions, with thread limits set to one. The preceding RED run reproduced the reported header/unit formula typing, undeclared CSV text and mechanics grid/ordering failures. New tests cover the actual on-disk Excel cell types, applying the CSV metadata schema to leading-zero text, explicit-grid interpolation on matching measured coordinates, rejected extrapolation and rejected loading/unloading reordering. Ruff passes all owned source, tests and examples. `examples/science/visualization/run_demo.py` completed 20 operation runs and wrote `artifacts/science-visualization-review-demo/visualization-demo.json`. It produced 14 PNG figures (13 figure types plus an explicit-grid mechanics example), normal/text-schema CSV and genuine XLSX/formula-text safety fixtures with readback, and self-contained HTML and Markdown reports.

The updated HTML report was opened through Playwright in installed headless Microsoft Edge: its actual title matched, all **14 embedded images** decoded (`complete && naturalWidth > 0`), and a screenshot was saved at `artifacts/science-visualization-review-demo/report-preview.png`. The original 13 figure previews were assembled into `artifacts/science-visualization-demo/figure-contact-sheet.png` and visually inspected; the standalone specimen-mean/error-band PNG was also inspected. Default bundled Playwright Chromium was absent; the installed Edge channel worked, with no downloads/environment changes. Integrated native Langflow/browser workflow checks remain owned by the parent task.


## science-materials.md

首轮 28 项测试覆盖上述解析与手工真值。独立复核再补充 8 项先失败后修复的回归，覆盖双 DSC 峰、TG 前平台与采集截断、数值舍入及拟合区间内交点、严格布尔配置、CMYK TIFF 和多组 EDS。单线程材料测试共 **36 项通过**。十条示例路径完成 CSV/JSON/PNG/NPY 回读，九个输入文件 SHA-256 前后一致。合成参考幅度约 2 和 3，DSC 为 150.39769647786 J/g，弹性模量为 200000 MPa，偏移屈服为 202.01005025125627 MPa，监督分割面积分数为 0.08。

并行运行本机 pytest 与示例时曾遇到一次 sklearn 内 Windows access violation；其前后的单独示例及串行材料测试均正常，尚不能据此确定原生运行时根因。最终串行复测设置 `OMP_NUM_THREADS=1`、`MKL_NUM_THREADS=1`、`OPENBLAS_NUM_THREADS=1`，分类器 `n_jobs=1`。完整项目测试与跨机器部署验证由集成流程记录。


## science-io.md

开发验证记录：首轮 28 个真实测试先失败于未实现的节点模块，随后全部通过；输入隔离与路径保护回归先复现原始文件被覆盖，再修复。后续补充跳转凭据、标头重名、旧转换文件、样品编号、整数精度与布尔类型回归。真实 OCR、PDF/图片、SQLite、SQLAlchemy、HTTP 服务、标定曲线及输出回读均纳入最终全套 415 项测试；原生图、独立 wheel 和真实网页验证见[整体验收](../full-suite-acceptance.md)。

## science-literature.md

开发执行记录：首先确认 5 个本地测试、3 个 HTTP 测试因缺实现而失败，再实现；小数分句和多声明来源串联各有先失败再修复的回归验证。公网结果与离线测试明确分开。


### science-statistics.md：原开发进度摘要

Progress: implemented all eight source entries and every listed method. Initial implementation passed 41 tests, the next design/security cycle passed 56, and independent review added 14 regression cases: 70 tests now pass. All 30 synthetic statistics/demo runs executed successfully. Integrated full-suite verification belongs to the parent task; this document claims the domain verification below.


### science-visualization.md：原开发进度摘要

Progress: all six source entries and all listed submethods implemented; the shared statistics/visualization suite now passes 70 synthetic numerical/roundtrip/security tests, including independent review regressions. Every figure carries its actual plot coordinates/aggregates in JSON-safe `NodeResult.data.plot_data`; consumers can inspect what was drawn. The module is `materials_quality.science.visualization`, with six independent CATALOG entries.
