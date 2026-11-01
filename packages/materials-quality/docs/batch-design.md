# 批量材料数据处理

目标：多文件或同表多样品复用一套流程；普通用户用 Langflow 原生文件选择、下拉、勾选、数值和规则表完成配置。
保持现有单文件流程与科学算法，保留旧 JSON 兼容入口。开发不更改 main 工作目录和既有运行环境。

## 数据与执行

- 使用 `materials-batch/1` Data 包在节点间传递整批任务，单项始终是一份完整文件或一组完整样品数据。
- 单项字段：`id`, `label`, `source`, `table`, `report`, `history`, `status`, `error`；可附带质量报告/待复核状态。
  source 包含 source_name/source_sha256/file_path（如有）。table 是可 JSON 序列化、保留类型/索引/单位的完整表。
  report 为最近一次 `science-result/1` 报告（入口允许简单文件元数据）；history 保存前序报告。
  status 为 `completed`/`failed`/`skipped`。批次标识在整条链中稳定，样品键唯一、顺序稳定。
- 批次字段：schema_version, batch_id, items, on_error（continue/stop）, counts, execution_status。
  逐项处理默认串行；一项技术错误可继续其他项并明确计数。全部失败不得显示成功。
- 文件入口允许原生多选；分组入口接受现有表格或一份表格文件，并通过实际列候选选择样品列。
  同名不同路径文件保持独立；缺失/歧义样品键拒绝分组。原文件不写入、不移动。
- 新增批量入口、批量质检、批量结果汇总三个组件。44 个科学节点通过共用适配器识别批次，
  复用现有单项算法；原有八个质检节点继续兼容单表，批量链用一个批量质检组件选择六项规则。
- 批量运行通过“结果与追溯”Data 端口串联；完整表数据不取自 100 行报告预览。
  报告、文件、失败与来源绑定到具体样品；不同项的输出目录隔离，不覆盖同名产物。
- 跨样品统计/训练必须显式选择整体输入，或从批量汇总的合并表输出连接到普通统计节点；
  材料单曲线拟合始终逐项处理，避免混合不同样品。首版可只通过汇总合并表实现整体统计。
- 批量汇总生成每样品指标、状态、错误、文件清单与 HTML 总报告；失败项保留记录与空缺指标。

## 原生交互与迁移

- 参考已安装 LFX1.13 的 Read File、Table Operations、Loop 控件与动态参数模式，不修改 Langflow 前端。
- 普通参数使用表单，复杂高级参数继续明确折叠；数据文件多选和样品列候选在真实浏览器中验收。
- 旧流程提供显式 `--prefer-forms` 迁移选项。旧节点参数能无损映射才转表单；保留原文件、节点ID和位置。
  未识别参数、自定义代码、不适用字段、旧条件输出连接均须保留并说明，不静默丢弃。
- 保留模型训练/已有模型/已有预测值任务含义；不能仅因表单默认值改变旧流程数值或 dispatch。
- 不掌握队友原流程时，不自动删除或折叠他的不同分析分支；用固定节点数的可导入示例证明批量能力。

## 接口与归属

`batch.packet`: SCHEMA, is_batch(value), pack_table(frame), unpack_table(payload),
make_item(item_id,label,source,table=None,report=None), make_batch(items,batch_id=None,on_error='continue'),
validate_batch(packet), combined_table(packet)。table 参数为 pandas.DataFrame 或 None，包中存编码值。
make_batch 计算计数与总体状态；传 batch_id 时保留身份。validate_batch 不执行路径或旧代码。

Parent：science/langflow_adapter.py、science/ui_schema.py、batch/execution.py、批量质检和汇总组件、示例与验收。
Task A：batch/packet.py、batch/source.py、components/materials_batch/batch_source.py 与专属测试。
Task B：science/flow_migration.py、science/ui_config_import.py、quality_form_import.py、迁移CLI与专属测试。
Task C：用户Markdown精简与开发记录归档；不修改数值定义、验收事实或源代码。

## 验收

20份拉伸数据使用同一条不随样品数增长的链；每项 E/屈服强度与单项基准一致；一项坏数据不混入其他项。
同表多样品分组得到对应结果；同名文件不覆盖；单位、前导零ID、非有限值、精度和来源可追溯。
真实网页多选上传、原生规则表编辑、下拉/数值设置、运行、汇总与图像解码通过，普通流程不填JSON。
旧流程迁移在保留语义、连线和结果的前提下优先表单。全套回归、wheel、main现有示例与最终独立复核通过。
