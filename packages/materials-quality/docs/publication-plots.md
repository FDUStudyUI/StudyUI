# 统一科研绘图规范

本轮把美赛、国赛绘图中可迁移的要求落实到项目：全精度数据、明确的图义、统一颜色与标记、
实际插图尺寸、单位与不确定性定义、矢量文字、文件回读和目视检查。绘图不添加未计算的显著性、
因果或实验结论，也不通过少画观测来改善外观。

## 使用

四类绘图节点及分布检查共用 `science/plot_style.py`。已有配置仍可运行，默认 `preview` 输出 PNG。
论文模式只需在“方法与参数 JSON”增加：

```json
{
  "profile": "paper",
  "data_kind": "synthetic",
  "width_mm": 150,
  "method": "box",
  "group": "group",
  "y": "stress",
  "units": {"stress": "MPa"},
  "labels": {"stress": "Peak stress"},
  "color_map": {"Baseline": "#0072B2", "Modified": "#D55E00"}
}
```

`data_kind` 可选 unspecified、synthetic、measured、simulated、derived，必须符合真实数据来源。
所有内嵌演示均标为 synthetic，图内可见该标识。缺少声明时不假称实测。

`paper` 默认 150 mm 宽，PNG 300 dpi、可编辑 SVG/PDF、600 dpi TIFF，附全精度绘图 JSON 和 Markdown 图注。
可设置 `height_mm`；旧 `figsize` 仍表示英寸。`formats` 可以显式选择 png/svg/pdf/tiff，始终保留 PNG 预览。
导出尺寸保留显式画布，不通过 tight 裁切改变尺寸。SVG 在计算哈希前统一为 LF 换行并清理行末空格，
确保 Windows/Linux 和 Git 检出后的校验值一致。超过 5000 万像素的栅格请求在分配之前拒绝。

## 图义与统计

- 同一系列保持稳定颜色、线型和标记；`color_map` 可明确指定跨图颜色。
- 柱、箱、小提琴图显示全部原始点及 n。小样本 KDE 给出探索性提示，不伪装成充分估计的分布。
- 柱图误差棒是样本 SD；箱线图为 Q1–Q3、中央中位线，须线按 1.5×IQR 范围确定。
- 力学误差带按试样曲线计算，区分 SD、SEM 和逐点 Student t 95% CI；区间不声称同时覆盖。
- 直方图区间须覆盖所有输入值；需要裁定范围时先在上游显式筛选，保留数据追溯。
- 预测与观测须使用相同单位或相同描述标签；不同尺度先上游换算，不在画图时暗中转换。
- 相关热图固定 -1～1 并标注 Pearson/Spearman/Kendall。相关不证明因果。

单位从表格属性、上游报告及显式配置合并，冲突会报错。预处理后的单位不会仅靠改坐标文字伪装成已换算。
每幅图保留输入表指纹、行列信息、全精度实际绘图数组、误差定义、字体、尺寸、各格式哈希和版面提示。
图指纹用于一致性检查，不证明来源真实。图注不会自动把提供的预测配对称为独立测试集。

## 可读性与集成

默认正文/刻度约 8–10 pt，白底、浅网格、深色文字。中文依赖运行电脑上的可用字体，自动考虑常用中文
字体；缺字提示写入警告。最终发表前仍需按实际插入宽度查看 PNG/PDF，检查缺字、重叠和图例。
Matplotlib 在项目内串行绘制，并恢复 rcParams；失败时只关闭本次创建的图，不改全局随机状态。

Langflow 的报告生成节点仅嵌入每幅逻辑图的 PNG 预览，避免把其 TIFF 再放一次。所有格式仍可从
“生成文件”端口找到。论文模式的九份工作流均可直接导入测试。

[六例完整画廊](../examples/paper_figures/README.md)提供现成数据、配置、图注与四格式文件。
参考技术依据：[Matplotlib 导出](https://matplotlib.org/stable/api/_as_gen/matplotlib.figure.Figure.savefig.html)、
[图例布局](https://matplotlib.org/stable/users/explain/axes/legend_guide.html)、
[无障碍色图](https://matplotlib.org/stable/users/explain/colors/colormaps.html)。
