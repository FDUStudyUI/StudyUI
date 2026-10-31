# 预处理与扩展质量检查

原始表格不变，预处理输出新表。所有操作返回参数、前后行列数和修改记录；归一化额外返回
拟合参数。`input_data` 与上游“结果与追溯”相连时，记录完整处理链；只有表格连线时记录本步输入指纹。

| 操作 | config_json 配置 | 约束 |
|---|---|---|
| `preprocess.filter` | `conditions:[{column,op,value}]`, `logic:and/or`, `columns`, `rename`, `drop_empty` | 仅白名单比较操作，不执行任意表达式 |
| `preprocess.missing` | `columns`, `method:keep/drop/mean/median/mode/ffill/linear`, `group_by` | 线性插值须显式声明 `continuous:true`、`order_by`；不外推；分组键须完整 |
| `preprocess.units` | `source_units:{stress:MPa}`, `target_units:{stress:Pa}` | Pint 校验量纲；支持带单位数值；保留原值和逐项换算记录 |
| `preprocess.reshape` | `method:melt/pivot/types`；具体字段见下方测试示例 | 长宽转换拒绝歧义；日期必须指定格式；整数不经浮点舍入 |
| `preprocess.merge` | `method:join/asof/append`, `on`, `how`, `validate`, `tolerance`, `by` | 默认一对一；拒绝空关联键；时间容差必须明确；记录关联来源 |
| `preprocess.normalize` | `columns`, `method:minmax/zscore/robust` | 返回中心与尺度；零 IQR 非恒定列不静默清零；模型训练使用独立训练集拟合预处理 |

可直接查看 `tests/test_science_preprocessing.py` 和 `test_science_preprocessing_review.py` 的
参数化示例。原生节点中的 JSON 配置就是纯函数 `config`，不需要写 Python 才能连线运行。

质量检查保留原有六项并补齐：JSON Schema Draft 2020-12 模板、字段类型推断、带转换审计的单位检查、
规范化文本相似匹配和显式数值容差。推断是建议，研究者仍须明确样品编号、类别与日期含义。
质量报告不会因无法换算的单元格丢失。关闭或受阻时，换算端口返回空表，报告说明原因；
只有完整成功的换算才输出转换值。JSON Schema 仅接受内部引用，不隐式联网加载外部规则。
换算与列改名同步维护单位，归一化列标为无量纲，导出拒绝互相矛盾的单位声明。

参考：[Pint 单位转换](https://pint.readthedocs.io/en/stable/user/converting.html)、
[JSON Schema 2020-12](https://json-schema.org/draft/2020-12)、
[pandas 合并说明](https://pandas.pydata.org/docs/user_guide/merging.html)。
