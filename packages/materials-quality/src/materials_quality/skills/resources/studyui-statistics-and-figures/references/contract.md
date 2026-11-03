# 组间研究任务接口

采用长格式输入。value_unit 显式声明，dimensionless 表示无量纲。design、experimental_unit 不自动猜测。
strategy 为 parametric/nonparametric；correction 为 holm/fdr_bh；alpha 位于 (0,1)。
输出 table 为技术重复聚合后的试验单位均值，features 为两两比较，groups 为描述统计，报告包含总体检验和校正范围。
不同 variable 共用声明单位；不同量纲应先拆分任务，或转换到同一明确单位。
