# 新手表单示例

这些流程不内嵌文件内容，练习在界面上传文件。先在 Langflow 导入 JSON，再按下表操作。
只需要本项目依赖，不需要个人 skill 或云端模型。

| 文件 | 上传内容和操作 |
|---|---|
| `mechanics.json` | 上传同目录 `synthetic-tensile.csv`；选择 strain/stress、fraction/MPa，拟合下限0、上限0.0008；运行最右侧报告节点。合成真值 E=200000 MPa，屈服应力约202.01 MPa。 |
| `image.json` | 上传同目录 `tiny.png`；运行报告节点，应得到13×7图像元数据，没有假空表格。 |
| `quality.json` | 上传同一CSV；共享规则默认要求 strain。把必需列改为 not_present 再运行结构检查，出现一条缺列发现。也可编辑数值范围规则表。 |
| `dynamic.json` | 方法从 median 切换为 linear，观察排序列和连续变量确认控件出现；真正运行线性插值前须按自己的数据填写排序与分组条件。 |

合成数据仅用于教学，不能用这些拟合区间代替真实实验的弹性区选择。
完整表单说明和共享规则操作见[使用指南](../../docs/node-usability.md)。

从包根目录运行 `python -m scripts.build_form_examples` 可重新生成这四份流程及两份合成文件。
运行将更新示例目录，其他运行产物在独立临时目录中生成。
