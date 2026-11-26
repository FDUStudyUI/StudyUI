# 原文要求与实现对照

50 项要求逐项保留原文。方法选择、必要输入和验证见对应手册；不能仅根据节点数量判断科学结论可靠。机器可读版本为 requirements-matrix.json。

| 编号 | 要求 | 操作 | 原文方法 | 方法说明 |
|---|---|---|---|---|
| 1.1 | 表格文件导入 | `io.table_import` | 识别分隔符与编码；选择工作表、表头行和数据区域。 | [手册](science-io.md) |
| 1.2 | 文本文件导入 | `io.text_import` | 识别编码；按行、分隔符或固定宽度解析。 | [手册](science-io.md) |
| 1.3 | PDF 文件导入 | `io.pdf_import` | 提取原生文本；扫描件转换为图像后交给 OCR。 | [手册](science-io.md) |
| 1.4 | 图片文件导入 | `io.image_import` | 读取图片格式、尺寸、分辨率和元数据。 | [手册](science-io.md) |
| 1.5 | 仪器文件导入 | `io.instrument_import` | 按仪器文件格式解析；暂不支持的格式使用转换器或插件。 | [手册](science-io.md) |
| 1.6 | 数据库接入 | `io.database_import` | SQL 查询；REST API 分页读取；按字段筛选。 | [手册](science-io.md) |
| 2.1 | PDF 文本提取 | `extract.pdf_text` | 按页提取；尽量保留段落和版面顺序。 | [手册](science-io.md) |
| 2.2 | PDF 表格提取 | `extract.pdf_tables` | 根据表格线提取；根据文本对齐关系提取；OCR 表格识别。 | [手册](science-io.md) |
| 2.3 | 图片文字识别 | `extract.image_ocr` | OCR；版面区域识别；保留文字位置与识别内容。 | [手册](science-io.md) |
| 2.4 | 图片表格提取 | `extract.image_tables` | 检测表格区域、切分单元格并识别单元格内容。 | [手册](science-io.md) |
| 2.5 | 图表数据提取 | `extract.chart_digitize` | 校准坐标轴；识别曲线；将曲线数字化为数据点。 | [手册](science-io.md) |
| 2.6 | 文件格式转换 | `extract.convert_file` | 解析原始格式或转换为 CSV、TXT、PNG 等中间格式。 | [手册](science-io.md) |
| 3.1 | 必需字段检查 | `quality.schema` | 必需列清单；字段名别名匹配；数据结构模板校验。 | [手册](../README.md) |
| 3.2 | 缺失值检查 | `quality.missing` | 统计数量和比例；按行、列、分组检查；分析缺失模式。 | [手册](../README.md) |
| 3.3 | 类型与格式检查 | `quality.types` | 推断字段类型；校验日期、数值和分类格式。 | [手册](../README.md) |
| 3.4 | 单位检查 | `quality.units` | 识别并换算单位；检查量纲兼容；标记混合单位。 | [手册](../README.md) |
| 3.5 | 重复记录检查 | `quality.duplicates` | 完全重复检查；按样品编号检查；相似记录匹配。 | [手册](../README.md) |
| 3.6 | 异常值识别 | `quality.outliers` | 按物理范围规则检查；四分位距法；MAD 稳健离群值检测。 | [手册](../README.md) |
| 4.1 | 行列筛选 | `preprocess.filter` | 按条件过滤；选择、重命名字段；移除空行。 | [手册](science-preprocessing.md) |
| 4.2 | 缺失值处理 | `preprocess.missing` | 删除记录；均值、中位数或众数填补；前向或线性插值；保留缺失。 | [手册](science-preprocessing.md) |
| 4.3 | 单位换算 | `preprocess.units` | 按明确的换算关系转换；保留原值和转换记录。 | [手册](science-preprocessing.md) |
| 4.4 | 格式转换 | `preprocess.reshape` | 宽表与长表转换；日期、数值和分类字段转换。 | [手册](science-preprocessing.md) |
| 4.5 | 多表合并 | `preprocess.merge` | 按样品编号连接；按时间或容差匹配；纵向追加。 | [手册](science-preprocessing.md) |
| 4.6 | 数据归一化 | `preprocess.normalize` | Min-Max；Z-score；稳健缩放。 | [手册](science-preprocessing.md) |
| 5.1 | XRD 数据处理 | `materials.xrd` | 背景扣除；平滑；峰检测；峰位与半高宽计算；物相匹配；全谱拟合。 | [手册](science-materials.md) |
| 5.2 | FTIR/Raman 数据处理 | `materials.spectra` | 基线校正；平滑；峰检测；峰面积计算；谱线归一化；谱库匹配。 | [手册](science-materials.md) |
| 5.3 | TG/DSC 热分析 | `materials.thermal` | 基线校正；失重阶段识别；峰温与起始温度计算；峰面积积分。 | [手册](science-materials.md) |
| 5.4 | 应力—应变分析 | `materials.mechanics` | 弹性模量拟合；屈服强度计算；最大强度识别；断裂应变与曲线积分。 | [手册](science-materials.md) |
| 5.5 | SEM/EDS 分析 | `materials.sem_eds` | 图像阈值分割；颗粒或孔隙识别；尺寸统计；读取元素定量结果。 | [手册](science-materials.md) |
| 5.6 | 显微结构图像分析 | `materials.microstructure` | 阈值或机器学习分割；连通区域分析；粒径、孔隙率和面积分数统计。 | [手册](science-materials.md) |
| 6.1 | 分组统计 | `stats.grouped` | 样本数、均值、标准差、中位数、四分位数、最小值和最大值。 | [手册](science-statistics.md) |
| 6.2 | 分布检查 | `stats.distribution` | 直方图、Q-Q 图；Shapiro-Wilk 正态性检验。 | [手册](science-statistics.md) |
| 6.3 | 相关性分析 | `stats.correlation` | Pearson；Spearman；Kendall。 | [手册](science-statistics.md) |
| 6.4 | 显著性检验 | `stats.significance` | 独立或配对 t 检验；Welch 检验；Mann-Whitney；ANOVA；Kruskal-Wallis。 | [手册](science-statistics.md) |
| 6.5 | 多重比较 | `stats.multiple` | Tukey；Dunn；Holm 校正；FDR 校正。 | [手册](science-statistics.md) |
| 6.6 | 回归分析 | `stats.regression` | 线性回归；多项式回归；岭回归；Lasso。 | [手册](science-statistics.md) |
| 6.7 | 预测模型 | `stats.predict` | 随机森林；梯度提升树；支持向量回归。 | [手册](science-statistics.md) |
| 6.8 | 模型评估 | `stats.evaluate` | 留出集验证；交叉验证；MAE、RMSE、R²。 | [手册](science-statistics.md) |
| 7.1 | 性能对比图 | `viz.performance` | 散点图、柱状图、箱线图、小提琴图。 | [手册](science-visualization.md) |
| 7.2 | 光谱或衍射图 | `viz.spectra` | 折线图、叠加谱图、差谱图、峰位标注。 | [手册](science-visualization.md) |
| 7.3 | 应力—应变图 | `viz.mechanics` | 曲线叠加；分组均值与误差带。 | [手册](science-visualization.md) |
| 7.4 | 统计图表 | `viz.statistics` | 直方图、相关性热图、残差图、模型预测图。 | [手册](science-visualization.md) |
| 7.5 | 结果表导出 | `export.table` | CSV、Excel；保留列名、单位和样品编号。 | [手册](science-visualization.md) |
| 7.6 | 分析报告生成 | `export.report` | 按模板汇总数据来源、节点参数、结果、图表和警告。 | [手册](science-visualization.md) |
| 8.1 | 文献搜索 | `lit.search` | 关键词、布尔检索、作者或 DOI 检索。 | [手册](science-literature.md) |
| 8.2 | 文献元数据提取 | `lit.metadata` | DOI 解析；提取题名、作者、期刊和年份。 | [手册](science-literature.md) |
| 8.3 | 材料与性能信息提取 | `lit.extract` | 规则和词典提取；表格解析；大模型结构化抽取并保留原文证据。 | [手册](science-literature.md) |
| 8.4 | 多篇文献对比 | `lit.compare` | 按材料、制备方法、测试条件和性能指标对齐比较。 | [手册](science-literature.md) |
| 8.5 | 引文与来源记录 | `lit.sources` | 保存 DOI、页码、表图编号和原文片段。 | [手册](science-literature.md) |
| 8.6 | 文献综述摘要 | `lit.summary` | 检索相关片段；基于证据生成摘要；为要点链接来源。 | [手册](science-literature.md) |
