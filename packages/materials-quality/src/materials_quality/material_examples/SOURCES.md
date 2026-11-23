# 真实仪器案例的数据来源

本目录收录 9 个公开仪器文件。原始字节保持不变；为方便跨平台使用，部分文件名缩短。`catalog.json` 保存原始压缩包成员路径、作者、DOI、许可、文件大小和 SHA-256。加载案例时检查哈希。

| 数据集 | 收录文件 | 原作者与许可 | 流程中的处理 |
|---|---|---|---|
| [FAIR Train: tensile testing data](https://zenodo.org/records/19007867)，DOI 10.5281/zenodo.19007867 | 铝、黄铜、1018 钢的 3 个 XLSX | Brian Schuster、Erwin Cazares、Edgar Tarin、Olga Wodo；CC BY 4.0 | 从 Sheet2 读取载荷和引伸计位移；依据原表面积、标距换算工程应力和应变；显式选择加载段、排序、拟合和偏移屈服计算 |
| [矿物 XRD 数据](https://zenodo.org/records/20032690)，DOI 10.5281/zenodo.20032690 | Amethyst、Graphite、Calcite 的 3 个 DAT | 作者完整记录见 catalog.json；CC BY 4.0 | 读取原始 2θ—强度数据，提取候选峰和结构化特征，不进行自动物相定论 |
| [PET 生物降解 Raman 数据](https://zenodo.org/records/20546300)，DOI 10.5281/zenodo.20546300 | SAMPLE 1、3、4 的 3 个 TXT | Pedari 等，Carleton University；作者完整记录见 catalog.json；CC BY 4.0 | 读取原始仪器注释、波数和计数；按声明突出度提取正峰 |

许可原文：[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/)。再分发这些数据时保留本文件和 `catalog.json`，标明后续修改。

力学案例的拟合区间固定为工程应变 0.0005–0.001，0.2% 偏移使用 fraction 单位。该选择服务于实现复核和选段敏感性展示。原仪器自动汇总采用的选段可能不同；评测单独记录与原汇总模量的差异，不调整参考值迎合本系统输出。

XRD、Raman 的突出度 100 使用原信号单位。这些案例展示数据接入、方法参数、特征输出和复现，不把公开文件数量解释为独立实验重复数。
