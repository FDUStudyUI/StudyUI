# 力学任务接口

应变单位 fraction 或 %；应力单位 Pa/kPa/MPa/GPa。fit_range 必须递增，采用输入应变单位。
sample_id 为样品列，或 single_sample=true 声明输入只有一份试样。组别可选且同一试样组别保持一致。
输出 table/features 为试样指标，curves 为所有成功试样的完整曲线，groups 为按组或全体的描述汇总。
全部试样失败时状态为 failed，部分失败为 partial_failed；生成报告不表示所有样品成功。
