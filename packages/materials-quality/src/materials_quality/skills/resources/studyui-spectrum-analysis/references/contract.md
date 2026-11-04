# 光谱任务接口

必须声明 curve_id、x、y、x_unit、y_unit、peak_window；group 可选。
窗口单位固定为 nm；波长输入单位通过单位系统换算。基线选 none/constant/linear；平滑默认关闭。
输出 table 为逐曲线摘要，features 为逐峰表，curves 为处理后完整曲线，groups 为候选峰分组描述。
谱线坐标不一致、每组少于两条或缺少所需支持时，绘图失败记警告并保留数值结果。
数据性质 data_kind 为 unspecified/synthetic/measured/simulated/derived；示例必须声明 synthetic。
