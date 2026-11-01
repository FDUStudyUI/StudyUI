"""Native search, extraction, provenance and summary controls for literature nodes."""

from .ui_types import field


def _provider():
    return [
        field(
            "provider",
            "元数据来源",
            "choice",
            default="local",
            choices=("local", "crossref"),
            info="local 仅处理上游记录/文本；crossref 通过网络检索公开元数据。",
        ),
        field(
            "base_url",
            "Crossref 服务地址",
            default="https://api.crossref.org",
            when={"provider": ["crossref"]},
            info="HTTP(S) 根地址；远程服务要求 HTTPS，本机服务可用 HTTP，不能嵌入凭据。",
        ),
        field(
            "timeout",
            "Crossref 超时（秒）",
            "float",
            default=20.0,
            when={"provider": ["crossref"]},
            info="大于 0 且不超过 60 秒；拒绝重定向并限制响应大小。",
        ),
    ]


def _llm():
    return [
        field(
            "llm.url",
            "LLM 完整接口地址",
            when={"method": ["llm"]},
            required=True,
            info="兼容聊天补全及 JSON Schema 的完整 HTTP(S) URL；远程要求 HTTPS。",
        ),
        field(
            "llm.model",
            "LLM 模型名",
            when={"method": ["llm"]},
            required=True,
            info="填写服务支持的模型标识；请求要求返回带精确原文与字符区间的声明。",
        ),
        field(
            "llm.api_key_env",
            "密钥环境变量名",
            when={"method": ["llm"]},
            required=True,
            info="只填写已设置的环境变量名称，如 OPENAI_API_KEY；不在工作流中填写密钥。",
        ),
        field(
            "llm.timeout",
            "LLM 超时（秒）",
            "float",
            default=20.0,
            when={"method": ["llm"]},
            info="大于 0 且不超过 60 秒；服务必须支持本节点的证据约束响应结构。",
        ),
    ]


SPECS = {
    "lit.search": [
        *_provider(),
        field(
            "method",
            "检索方式",
            "choice",
            default="keyword",
            choices=("keyword", "boolean", "author", "doi"),
            info="布尔检索支持 AND、OR、NOT、括号和引号短语；Crossref 仅过滤有限候选集。",
        ),
        field(
            "query",
            "检索词 / DOI",
            default="ZnO",
            required=True,
            info="关键词、作者、布尔表达式或 DOI；本地模式从上游表或 Data.records/documents 检索。",
        ),
        field(
            "rows",
            "Crossref 候选数量",
            "int",
            default=20,
            when={"provider": ["crossref"]},
            info="1 至 1000 的整数；DOI 查找使用单篇结果，不保证关键词/布尔检索召回完整。",
        ),
    ],
    "lit.metadata": [
        *_provider(),
        field("doi", "直接查询 DOI", info="无上游文档时可填写 DOI；Crossref 模式要求每份文档带 DOI。"),
    ],
    "lit.extract": [
        field(
            "method",
            "提取方式",
            "choice",
            default="regex",
            choices=("regex", "lexicon", "table", "llm"),
            info="从上游含 text 的表或 Data.documents 提取，并保留来源 ID、原文与字符区间。",
        ),
        field(
            "patterns",
            "属性 → 正则表达式",
            "dict",
            default={"strength": r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>MPa|GPa)"},
            when={"method": ["regex"]},
            required=True,
            info=("键为属性名，值为正则；命名组 value/unit 提取数值和单位。每条表达式最长 2000 字符。"),
        ),
        field(
            "lexicon",
            "属性 → 术语列表",
            "dict",
            converter="list_mapping",
            when={"method": ["lexicon"]},
            required=True,
            info="普通键值编辑器：键为属性名，值为逗号分隔的术语；逐条执行忽略大小写的字面匹配。",
        ),
        field(
            "delimiter",
            "表格分隔符",
            default=",",
            when={"method": ["table"]},
            required=True,
            info="必须恰好一个字符；文本首行为唯一列名，每个物理行对应一行数据且列数一致。",
        ),
        *_llm(),
    ],
    "lit.compare": [
        field(
            "target_units",
            "属性 → 目标单位",
            "dict",
            default={},
            info=(
                "例如 strength → MPa；留空保留原单位。输入需有 "
                "material/preparation/test_condition/property/value/unit/source_id。"
            ),
        ),
        field(
            "relative_tolerance",
            "差异标记相对容差",
            "float",
            default=0.0,
            info="有限非负数；同材料、制备、测试条件、属性与归一化单位内比较，不等同于显著性检验。",
        ),
    ],
    "lit.sources": [
        field(
            "save",
            "保存来源记录文件",
            "bool",
            default=False,
            info="始终返回来源记录表；开启后另写 literature-sources.json，精确检查原文和字符区间。",
        ),
        field(
            "output_dir",
            "保存目录",
            when={"save": [True]},
            info="可选本机目录；留空创建临时目录，仅开启保存时使用。",
        ),
        field(
            "overwrite",
            "覆盖同名文件",
            "bool",
            default=False,
            when={"save": [True]},
            info="关闭时为已有文件生成唯一文件名，保留以前的来源记录。",
        ),
    ],
    "lit.summary": [
        field(
            "method",
            "摘要方式",
            "choice",
            default="extractive",
            choices=("extractive", "llm"),
            info="按问题检索原文片段；extractive 直接引用，llm 对检索命中的来源生成受证据约束的声明。",
        ),
        field(
            "question",
            "检索与归纳问题",
            default="strength",
            required=True,
            info="必填；按词语重叠排序原文片段，无命中时返回真实空表及提示。",
        ),
        field(
            "top_k",
            "最多检索片段数",
            "int",
            default=5,
            info="1 至 100 的整数；LLM 模式提交命中片段所属的完整来源文本以保留字符区间。",
        ),
        *_llm(),
    ],
}


# All six functions explicitly construct a DataFrame, including zero matches.
# Only sources can write an artifact, and only when save=True. None reads uploads.
CONTRACTS = {
    "lit.search": {"table_output": True, "artifacts_output": False, "upload_types": [], "icon": "Search"},
    "lit.metadata": {"table_output": True, "artifacts_output": False, "upload_types": [], "icon": "BookOpen"},
    "lit.extract": {"table_output": True, "artifacts_output": False, "upload_types": [], "icon": "ScanText"},
    "lit.compare": {"table_output": True, "artifacts_output": False, "upload_types": [], "icon": "Columns3"},
    "lit.sources": {"table_output": True, "artifacts_output": True, "upload_types": [], "icon": "Quote"},
    "lit.summary": {
        "table_output": True,
        "artifacts_output": False,
        "upload_types": [],
        "icon": "NotebookPen",
    },
}
