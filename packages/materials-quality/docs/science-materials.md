# 材料专业分析：六个节点与可复现验证

实现入口为 `materials_quality.science.materials`。本文件对应《材料科学节点与方法》第 5 节的全部六项及所列子方法。全部方法操作输入副本，原始表格、图片和文件不被分析过程修改。示例全部为**合成数据**，不代表真实材料鉴定结果。

## 运行示例

在 `packages/materials-quality` 目录、已安装本项目及科学计算依赖的 Python 环境中运行：

```powershell
$env:PYTHONUTF8 = '1'
$env:MPLBACKEND = 'Agg'
python examples/science/materials/run_demo.py
python -m pytest tests/test_science_materials.py tests/test_science_materials_review.py --basetemp artifacts/pytest-materials-local -q
```

示例生成器将带 `synthetic_` 前缀的输入写入 `examples/science/materials/fixtures/`，执行十种配置路径，结果写入 `artifacts/materials-demo/`。它会回读全部 CSV、JSON、分割 PNG 和标签 NPY，并核对分析前后输入文件 SHA-256。`verification.json` 记录执行路径、哈希和回读结果。再次运行生成器会重新生成这些明确标识的合成输入；分析函数本身不覆盖输入。

依赖：NumPy、pandas、SciPy、Pillow、scikit-image；监督分割另需 scikit-learn。无需在线账户或密钥。实际 XRD/光谱匹配须自行提供有使用权限的参考谱库；实际图像须提供空间校准；EDS 元素含量必须先由外部仪器软件等完成定量。

```python
import pandas as pd
from materials_quality.science.materials import mechanics

result = mechanics(pd.read_csv("tensile.csv"), config={
    "x": "strain", "y": "stress",
    "strain_unit": "%", "stress_unit": "MPa",
    "fit_range": [0.02, 0.08],
    "yield_offset": 0.002,
})
print(result.data)
print(result.warnings)
```

原生节点的 JSON 配置对应 `config`。DataFrame 输入对应 `table`，结构化 Data 对应 `data`。六个函数均支持统一签名 `fn(table=None, *, config=None, data=None, tables=None)`；本组不使用多表输入 `tables`。

## 公共曲线输入、输出与边界

- 默认横、纵列名为 `x`、`y`；力学默认 `strain`、`stress`，均可通过配置 `x`/`y` 修改。
- 至少三个点，所有值必须有限且可转换为数值；不默认填补 NaN。横坐标须严格递增。`sort: true` 可明确排序，但重复横坐标仍报错。降温、加载卸载回线等必须先按物理过程分段，不能靠排序合并。
- 输出表保留 `source_row`（输入中的零基行位置）、`x`、`raw_y`，以及适用的 `baseline`、`corrected`、`smoothed`、`normalized`、`fitted`、`residual`。`data.transform` 保存配置、来源列、受影响行数、排序事实和原始保留标志。
- 背景/基线 `baseline`：`{"method":"none"}`（默认，等价于零基线）；`{"method":"constant","value":1}`；`{"method":"linear"}`（首尾测量点连线）；`{"method":"anchors","points":[[x0,y0],[x1,y1],...]}`（明确锚点间线性插值）。锚点必须覆盖测量范围；不外推、不自动猜测无峰区域。
- 平滑 `smooth_window` 默认 0（不平滑）；开启时须为不超过点数的奇数，且大于 `smooth_order`（默认 2）。采用 Savitzky–Golay，要求等间隔横坐标；不隐式重采样。
- 峰检测使用 SciPy `find_peaks`，`prominence` 为信号单位下的正数，默认全程极差的 5%；`peak_distance` 为样本点数，默认 1。峰位为检测样本的横坐标。
- `area_ranges` 为一组测量范围内的 `[下限,上限]`，默认全范围。边界落在样本间时线性插值边界，随后梯形积分。禁止范围外外推。所有光谱积分都在归一化之前进行。

## XRD：`materials.xrd`

| 所需子方法 | 实现及配置 | 结果证据 |
|---|---|---|
| 背景扣除、平滑 | 上述 `baseline`、`smooth_window` | 原始、背景、扣背景、平滑四条曲线 |
| 峰检测、峰位 | `prominence`、`peak_distance` | `data.peaks` 中样本索引、位置、高度、突出度 |
| 半高宽 | 基线扣除后峰高的 1/2，两侧最近交点线性插值 | `fwhm`，缺少交点为 null 并警告 |
| 物相匹配 | `match: "profile"` 或 `"peaks"`，实际供给参考库 | `matches` 含名称、分数、指标、来源，峰表还含逐峰匹配与覆盖率 |
| 全谱拟合 | `whole_pattern: "reference"` 或 `"gaussian"` | 拟合曲线、残差、RMSE、R²、系数或峰参数 |

参考谱以 `data.references`（或 `config.references`）传入：

```json
{"references": [{
  "name": "用户提供的参考名称", "source": "数据库记录号或文件来源",
  "x": [10, 11, 12, 13], "y": [0, 1, 0.3, 0], "x_unit": "degree_2theta"
}]}
```

此时测量配置也必须明确同一 `x_unit`；没有填参考单位时不隐式推定或换算单位。参考曲线必须非负、非零、横坐标递增并覆盖测量范围；插值后在测量范围内仍须有非零信号。参考名称不得重复。

`match: "profile"` 采用相同测量坐标上的余弦相似度。`match: "peaks"` 使用 `{"name":"...","peaks":[20.1,30.2],"source":"..."}`，`match_tolerance` 默认 0.1 个横坐标单位；采用一对一最小距离分配，容差内匹配，报告测量范围内峰表 F1、两侧覆盖率、范围外参考峰数。不会把同一个观测峰多次分配给参考峰。

`whole_pattern: "reference"` 为**用户参考全谱的非负线性组合**，使用 NNLS；线性相关参考会因系数不可辨识报错。系数是原始参考幅度的比例，**不等于物相质量分数**。

`whole_pattern: "gaussian"` 为**经验高斯峰叠加模型**，必须传入初值：

```json
{"whole_pattern":"gaussian", "fit_peaks":[
  {"center": 25.0, "sigma": 0.4, "amplitude": 100},
  {"center": 42.0, "sigma": 0.7, "amplitude": 60}
]}
```

拟合所有测量点，振幅非负、中心限定于测量范围、宽度为正，输出各峰中心、sigma、FWHM、面积及收敛状态。两种模型均明确 `structural_refinement: false`，不声称做晶体结构 Rietveld 精修。经验拟合可能存在局部最优，重叠峰可能不可辨识；未作仪器展宽校正或绝对物相确认。

半高宽有意不直接采用 `scipy.signal.peak_widths(..., rel_height=0.5)`：该 API 默认计算半突出度宽度，不总是基线扣除峰高的半高宽。见 [SciPy peak_widths 定义](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.peak_widths.html)。非负谱系数模型见 [SciPy NNLS 文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.nnls.html)。

## FTIR/Raman：`materials.spectra`

包含基线、平滑、峰检测、每峰两侧基底间面积、明确区间面积、归一化和实际谱库匹配。归一化 `normalization` 支持 `none`、`max`（最大绝对值）、`l2`（采样向量二范数）、`area`（绝对信号对横坐标积分）；零谱不可归一化。原始有符号峰面积与归一化因子分别保存。

参考谱合同及 `match` 与 XRD 一致；谱库分数不等于化学结构确认。FTIR 应提供适合的信号约定，例如吸光度。不会自动将透过率转为吸光度，也不会假设上下峰的化学含义。各峰基底区间可能相互重叠；做定量时用互不重叠的 `area_ranges` 指定积分范围。

## 热分析：`materials.thermal`

`kind` 为 `tg`（默认）或 `dsc`。必须声明横坐标单位 `x_unit: "degC" | "K" | "s" | "min"`。输出坐标保持原单位，不把 K 绝对温度误标为摄氏度。

TG 支持的 `y_unit` 为 %、mg 或 g。基线代表加性漂移，校正质量须非负。默认用校正后初始质量归一化，也可通过同一质量单位的 `initial_mass` 给定参考质量。输出归一化质量、负质量导数、总失重百分比。`stage_threshold` 是每横坐标单位的百分比失重速率阈值，默认最大正失重速率的 5%。超阈值连通区间确定阶段边界和阶段内失重。阈值两侧尾部不计入阶段失重，因此各阶段之和可以小于全程失重。

求起始温度时，节点独立检查本事件峰前、上一事件最大失重速率点之后的实测平台。平台取最后一段连续至少三个样本、绝对质量变化速率不超过本事件峰值速率 1% 的区间。最大失重速率点的切线与这段平台的质量中位数相交得到起始坐标。`plateau_range`、`plateau_rate_limit` 和 `baseline_level` 给出采用的观测证据。未观察到平稳平台或交点越出已观察范围时，`onset` 返回 null 并附警告。

DSC 要求给定仪器符号约定 `endotherm: "positive" | "negative"`。校正基线之上的局部极大值和基线之下的局部极小值分别按该约定标记吸热或放热。同方向相邻峰使用峰间谷处分界，发生极性反转时使用基线穿越处分界。各事件报告自己的上升沿区间 `leading_range`，其最大斜率切线与零基线相交为起始位置。交点落在已观察领先段之外时返回 null。仅当横坐标为温度时设置 `peak_temperature`。

DSC 单位换算：

| 输入 `y_unit` | 结果积分单位 |
|---|---|
| `W/g` 或 `mW/mg` | J/g |
| `mW/g` | J/g（功率乘 0.001） |
| `W` | J |
| `mW` | J（功率乘 0.001） |

时间轴 `s` 直接积分；`min` 乘 60。温度轴要求正的恒定 `heating_rate`，并给 `heating_rate_unit: "K/min" | "K/s" | "degC/min" | "degC/s"`；例如 10 K/min 时 `dt = 6 dT` 秒。直接输出有符号 `enthalpy` 和统一为吸热正的 `endothermic_positive_enthalpy`。J 输出不会在缺少样品质量时变成 J/g。变升温速率数据应提供实际时间轴；本实现不处理温度反向或冷却扫描。基线选择及重叠转变会影响积分，没有自动反卷积。

## 力学：`materials.mechanics`

仅处理单调工程拉伸曲线。`strain_unit: "fraction" | "%"` 和 `stress_unit: "Pa" | "kPa" | "MPa" | "GPa"` 必填；统一以无量纲应变和 MPa 计算。

- `fit_range` **必填，以输入应变单位给定**，包含至少三个实测点。输出最小二乘弹性模量（MPa）、截距、R²、采用的原始行号。拟合区间不会被自动猜测；R² 低于 0.99 提示检查。
- `yield_offset` 默认 0.002，**始终是无量纲应变**（0.2%），与输入是否为百分数无关。屈服强度是弹性拟合线向右平移后的首次测量交点，用线性插值求位置；没有测到交点则 null 并警告，不外推。
- 最大强度取实际最大应力及其应变。末端应变默认仅为 `last_measured_strain`；只有 `fracture_confirmed: true` 才同时输出 `fracture_strain`，需要实验断裂证据。
- 曲线有符号积分 `work_density_MJ_m3 = ∫stress_MPa d(strain_fraction)`，积分覆盖实际测量区间，不自动补到零点。此处并不把缺少完整断裂的积分称为完整断裂韧性。

`sort` 和 `fracture_confirmed` 只接受实际 JSON 布尔值。字符串 `"false"` 会报错。求偏移屈服交点时只将浮点精度内的应力残差视为零，并检查插值交点本身位于拟合区间之后和偏移应变处或之后。

输入应为单调拉伸工程量。试验机柔度、夹持滑移和真实应力应变的校正需要试验侧信息。

## SEM/EDS 与显微结构

`materials.sem_eds` 的 `method` 为 `image`（默认）或 `eds`。`materials.microstructure` 直接进入图像分析。图像输入：`data.image` 数值数组，或 `config.path` / 上游 `data.file_path` 指向真实图片。彩色图像转为亮度；灰度图保留原强度尺度。阈值必须与该尺度一致。

图像配置：

| 参数 | 说明 |
|---|---|
| `segmentation: "threshold"` | 默认阈值分割；`threshold` 为数值或默认 `"otsu"` |
| `foreground: "bright" / "dark"` | 大于阈值或小于等于阈值的部分是目标 |
| `feature: "particle" / "pore" / "grain"` | 由用户明确解释区域含义，算法不判断材料身份 |
| `connectivity: 1 / 2` | 四邻接或八邻接连通区域，默认 1 |
| `min_area_pixels` | 删除小于此像素面积的前景连通区域，默认 1；记录过滤前后面积分数 |
| `pixel_size` + `spatial_unit` | 正的各向同性每像素尺寸及单位标签，例如 0.05 和 um；两项必须同时提供 |
| `output_dir` | 掩膜 PNG 与整数标签 NPY 的输出目录；默认新临时目录 |

文件读取保留原生灰度图的数值尺度。CMYK 等彩色文件先按 Pillow 颜色模式转换为 RGB，再计算亮度。直接传入的四通道数值数组约定为 RGBA。

缺少空间校准时输出 px、px²并警告，不伪造物理粒径。区域表输出面积、等面积圆直径、二阶矩椭圆主/次轴长度、质心和接触图像边界标志；汇总粒径均值、中位数、样本标准差、极值。孔隙 `feature: "pore"` 才输出 `porosity_area_fraction`；所有情况输出目标面积分数。像素区域测量定义见 [scikit-image regionprops](https://scikit-image.org/docs/stable/api/skimage.measure.html#skimage.measure.regionprops)。

`segmentation: "ml"` 启用真正的 sklearn 随机森林像素分类器，须提供与图像同形状的 `data.training_labels`：-1 未标注，0 背景，1 前景，必须包含两类。默认 `ml_features: "intensity"` 使用强度；`"multiscale"` 增加 sigma 1/2 高斯、梯度及局部方差特征，需有代表性的内部和边界标注。`random_state` 默认 0，100 棵树。输出训练像素计数、类别计数、特征和随机种子。没有虚构预训练模型，也不把同图推断当作独立验证准确率。

区域只是二维连通图像特征；接触的颗粒/晶粒不会自动拆开，面积分数不直接证明三维孔隙率。图像上的比例尺、文字和伪影须先明确裁除或遮蔽；本组不会识别并删除它们。边界截断区域保留并提示。

EDS 模式支持现成 DataFrame 或 `config.path` 的 CSV。默认元素列为 `element`，可用 `element_column` 改名。数值列默认检测 `wt_percent` 和 `at_percent`，或由 `percent_columns` 指定。检查有限值、0–100 范围和每个成分的百分比总和，保留外部原值。多测点样品必须提供成分标识列，例如 `{"method":"eds","group_by":"spot"}`。每个成分应每种元素一行，重复元素会报错。每组总和见 `group_totals`。仅一个成分时 `totals` 兼容原输出，多个成分时 `totals` 为 null。单组总和偏离 100 超过 1 个百分点给出该组提示。节点接收仪器软件已定量的元素数据，输出来源标记为 externally supplied。

## 测试矩阵与执行记录

测试文件 `tests/test_science_materials.py` 的主要独立真值：

| 方法 | 解析或手工真值 |
|---|---|
| XRD 半高宽 | sigma=1.2 高斯，FWHM=2.82578，峰位 0 |
| 参考全谱拟合 | 两个已知高斯参考的 2:3 幅度组合 |
| 经验全谱拟合 | 中心 6/13、sigma 0.6/1.1 的双峰 |
| 光谱积分 | 高度 2、sigma 1 高斯，面积 5.01325655 |
| DSC 积分 | 高度 2 W/g、sigma 5 K、10 K/min，150.3976965 J/g |
| DSC 符号与时间 | -2 mW，2 分钟，-0.24 J；吸热负时归一符号为 +0.24 J |
| TG | 20 mg→16 mg，20% 总失重，最大失重位置 50，切线起始约 46 |
| 拉伸 | E=200000 MPa，0.2% 屈服 202.01005025 MPa，UTS 219 MPa，积分 4.0805 MJ/m³ |
| 图像 | 12+20 像素区域，占 20×20 图像 8%；2 um/px 对应 48/80 um² |
| 监督分割 | 二值合成目标、真实给定标签，已知区域面积；无标签拒绝 |
| EDS | CSV 和表格读取 Si/O 46.7/53.3，原值及总量不变 |

边界检查包括无参考库、覆盖不全/仅范围外有信号、无序/重复坐标、NaN、范围外积分、非均匀平滑、缺单位/升温速率/吸热符号、缺弹性拟合区间、未测到屈服、常量图、零校准、负 EDS 百分比、暗孔隙和小区域过滤、PNG 原文件字节不变。

首轮 28 项测试覆盖上述解析与手工真值。独立复核再补充 8 项先失败后修复的回归，覆盖双 DSC 峰、TG 前平台与采集截断、数值舍入及拟合区间内交点、严格布尔配置、CMYK TIFF 和多组 EDS。单线程材料测试共 **36 项通过**。十条示例路径完成 CSV/JSON/PNG/NPY 回读，九个输入文件 SHA-256 前后一致。合成参考幅度约 2 和 3，DSC 为 150.39769647786 J/g，弹性模量为 200000 MPa，偏移屈服为 202.01005025125627 MPa，监督分割面积分数为 0.08。

并行运行本机 pytest 与示例时曾遇到一次 sklearn 内 Windows access violation；其前后的单独示例及串行材料测试均正常，尚不能据此确定原生运行时根因。最终串行复测设置 `OMP_NUM_THREADS=1`、`MKL_NUM_THREADS=1`、`OPENBLAS_NUM_THREADS=1`，分类器 `n_jobs=1`。完整项目测试与跨机器部署验证由集成流程记录。
