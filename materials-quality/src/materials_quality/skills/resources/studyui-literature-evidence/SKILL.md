---
name: studyui-literature-evidence
description: 规划与执行可复核的科研论文检索，核实 DOI、元数据、研究类型、数据可得性和证据边界；用于方法查找、复现、文献综述和科研工作流依据。
metadata:
  version: "1.0.0"
  domain: "scholarly-literature"
  triggers: "literature search|literature review|find papers|search papers|DOI|citation|research method|paper evidence|论文检索|文献检索|文献综述|查论文|找文献|文献证据|研究方法|实验方法|材料方法|引用核验|DOI核验|公开数据集|论文复现"
---

# 科研文献证据检索

1. 先说明检索问题：材料/化学体系、方法或性质、比较条件、证据年份/文献类型及用户要做的决定。将检索式扩成核心术语、同义词、缩写和必要排除词；避免只靠一条自然语言查询。
2. 只调用 StudyUI 已登记的学术索引服务（Crossref、OpenAlex、Semantic Scholar、Europe PMC），遵守用户指定数据库/年份/文献类型。此工具检索到的元数据或摘要不等于全文获取，不声称读过未读取的全文、图表或补充材料。
3. 优先识别原始研究、方法论文、综述、标准/指南和数据论文。方法参数、性能数字及因果结论尽量追到原始研究或标准来源；综述用于定位而非替代一手证据。
4. 去重并核对标题、作者、年份、期刊和 DOI。DOI 需对应到目标论文；无法核实的 DOI 标为未确认，不能拼造引用。
5. 对每个候选记录：检索来源/查询、书目信息、DOI/链接、文献类型、可见摘要/元数据范围、材料体系、数据/方法可得性和与任务的相关理由。明确写出筛选标准以及可能遗漏的数据库/语言/时间范围。
6. 若用户给了开放数据仓储，先核对其 README、记录元数据、文件树与版本；用数据字典匹配字段，不能仅因相关论文/数据集“公开”就声称 Agent 已读取原始文件。
7. 将论文中的结论与 StudyUI 工作流结果分开。论文值可用于对照，但不能假装本地计算已复现论文；不同样品、仪器、处理和实验条件需要解释差异。
8. 只在用户要求或工作流参数确实依赖证据时搜索。已给出充分数据说明且任务只是构图时避免重复检索；未知方法参数应标待核实，而非从相似论文借值填充。

## 参考

- [Crossref](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)：学术出版元数据检索。
- [OpenAlex](https://docs.openalex.org/)：开放学术作品/作者/机构索引。
- [Semantic Scholar API](https://api.semanticscholar.org/api-docs/)：学术文献元数据与摘要服务。
- [Europe PMC REST API](https://europepmc.org/RestfulWebService)：生物医学及相关文献检索；只用于其索引覆盖范围。
