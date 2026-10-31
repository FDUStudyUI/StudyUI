"""Traceable literature discovery, extraction, comparison, and extractive reviews."""

import csv
import io
import json
import math
import re
from copy import deepcopy
from urllib.parse import quote as urlquote

import pandas as pd

from .contracts import NodeResult, artifact_path, require_table
from .lit_evidence import LOCATION_FIELDS, citation, documents, evidence, llm_claims, request_json

DOI = re.compile(r'10\.\d{4,9}/[^\s<>"\x00-\x1f]+', re.I)


def _doi(value):
    match = DOI.search(str(value))
    if not match:
        raise ValueError("provide a valid DOI (10.<registrant>/<suffix>)")
    return match.group().rstrip(".,;:)]}").lower()


class _Boolean:
    """Recursive descent parser: NOT > AND > OR; no expression evaluation."""

    def __init__(self, query):
        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            raise ValueError("Boolean query must be nonempty and at most 4000 characters")
        self.tokens = re.findall(r'"[^"\n]+"|\(|\)|\bAND\b|\bOR\b|\bNOT\b|[^\s()"]+', query)
        if "".join(self.tokens).replace(" ", "") != re.sub(r"\s+", "", query):
            # Quoted whitespace is valid; compare after removing all whitespace.
            if re.sub(r"\s+", "", "".join(self.tokens)) != re.sub(r"\s+", "", query):
                raise ValueError("Boolean query has an invalid quote/token")
        self.position = 0
        try:
            self.tree = self._or()
            if self.position != len(self.tokens):
                raise ValueError("unexpected token")
        except (IndexError, RecursionError, ValueError):
            raise ValueError("Boolean syntax requires terms, AND/OR/NOT, balanced parentheses") from None

    def _take(self, token):
        if self.position < len(self.tokens) and self.tokens[self.position] == token:
            self.position += 1
            return True
        return False

    def _or(self):
        node = self._and()
        while self._take("OR"):
            node = ("OR", node, self._and())
        return node

    def _and(self):
        node = self._atom()
        while self._take("AND"):
            node = ("AND", node, self._atom())
        return node

    def _atom(self):
        if self._take("NOT"):
            return ("NOT", self._atom())
        if self._take("("):
            node = self._or()
            if not self._take(")"):
                raise ValueError("missing parenthesis")
            return node
        token = self.tokens[self.position]
        if token in {"AND", "OR", ")"}:
            raise ValueError("expected term")
        self.position += 1
        return ("TERM", token.strip('"').casefold())

    def matches(self, text):
        def visit(node):
            if node[0] == "TERM":
                return node[1] in text.casefold()
            if node[0] == "NOT":
                return not visit(node[1])
            if node[0] == "AND":
                return visit(node[1]) and visit(node[2])
            return visit(node[1]) or visit(node[2])

        return visit(self.tree)


def _crossref_record(item):
    def first(field):
        value = item.get(field)
        return value[0] if isinstance(value, list) and value else value or None

    date = next(
        (item.get(k) for k in ("published", "published-print", "published-online", "issued") if item.get(k)),
        {},
    )
    parts = date.get("date-parts", [[]])
    return {
        "doi": item.get("DOI"),
        "title": first("title"),
        "authors": [
            " ".join(filter(None, [a.get("given"), a.get("family")])) or a.get("name")
            for a in item.get("author", [])
        ]
        or None,
        "journal": first("container-title"),
        "year": parts[0][0] if parts and parts[0] else None,
        "url": item.get("URL"),
        "metadata_provider": "crossref",
    }


def _crossref(config, doi=None, params=None):
    base = config.get("base_url", "https://api.crossref.org").rstrip("/")
    path = "/works" + ("/" + urlquote(doi, safe="") if doi else "")
    result = request_json(
        base + path,
        config=config,
        params=params,
        headers={"User-Agent": "MaterialsQuality/0.3 (literature metadata)"},
    )
    if not isinstance(result, dict) or not isinstance(result.get("message"), dict):
        raise ValueError("Crossref response must contain a message object")
    message = result["message"]
    if doi:
        if "DOI" not in message:
            raise ValueError("Crossref work response lacks DOI")
        return [_crossref_record(message)]
    if not isinstance(message.get("items"), list):
        raise ValueError("Crossref search response lacks items")
    return [_crossref_record(x) for x in message["items"]]


def search(table=None, *, config=None, data=None, tables=None):
    cfg = config or {}
    method, provider = cfg.get("method", "keyword"), cfg.get("provider", "local")
    if method not in {"keyword", "boolean", "author", "doi"}:
        raise ValueError("method must be keyword, boolean, author, or doi")
    query = cfg.get("query", cfg.get("doi", ""))
    if not isinstance(query, str) or not query.strip():
        raise ValueError("search query is required")
    expression = _Boolean(query) if method == "boolean" else None
    if provider == "local":
        records = (
            require_table(table).to_dict("records")
            if table is not None
            else deepcopy((data or {}).get("records", (data or {}).get("documents", [])))
        )
        if not isinstance(records, list):
            raise ValueError("local search requires data.records list")
    elif provider == "crossref":
        rows = cfg.get("rows", 20)
        if type(rows) is not int or not 1 <= rows <= 1000:
            raise ValueError("rows must be an integer in [1, 1000]")
        if method == "doi":
            records = _crossref(cfg, doi=_doi(query))
        else:
            field = "query.author" if method == "author" else "query.bibliographic"
            candidate = (
                " ".join(t.strip('"') for t in expression.tokens if t not in {"AND", "OR", "NOT", "(", ")"})
                if expression
                else query
            )
            records = _crossref(cfg, params={field: candidate, "rows": rows})
    else:
        raise ValueError("provider must be local or crossref")
    selected = []
    for record in records:
        text = " ".join(str(record.get(k) or "") for k in ("title", "authors", "journal", "abstract", "text"))
        if method == "doi":
            match = bool(record.get("doi")) and _doi(record["doi"]) == _doi(query)
        elif method == "author":
            match = query.casefold() in str(record.get("authors", "")).casefold()
        elif expression:
            match = expression.matches(text)
        else:
            match = all(token.casefold() in text.casefold() for token in query.split())
        if match:
            selected.append(record)
    bounded = provider == "crossref" and method == "boolean"
    return NodeResult(
        table=pd.DataFrame(selected),
        data={
            "provider": provider,
            "method": method,
            "query": query,
            "candidate_count": len(records),
            "candidate_filtering": bounded,
            "records": deepcopy(selected),
        },
        warnings=[
            "Crossref Boolean filtering applies only to the bounded ranked candidate set; "
            "recall is incomplete."
        ]
        if bounded
        else [],
    )


def metadata(table=None, *, config=None, data=None, tables=None):
    cfg = config or {}
    provider = cfg.get("provider", "local")
    docs = documents(table, data) if table is not None or data else []
    if not docs and cfg.get("doi"):
        docs = [{"source_id": "doi-1", "text": cfg["doi"], "doi": cfg["doi"]}]
    if not docs:
        raise ValueError("provide documents, a text table, or config.doi")
    if provider not in {"local", "crossref"}:
        raise ValueError("provider must be local or crossref")
    records = []
    for doc in docs:
        match = DOI.search(doc["text"])
        doi = _doi(doc.get("doi") or match.group()) if doc.get("doi") or match else None
        if provider == "crossref":
            if not doi:
                raise ValueError("Crossref metadata lookup requires DOI in each document")
            row = _crossref(cfg, doi=doi)[0]
        else:
            row = {
                "doi": doi,
                "title": None,
                "authors": None,
                "journal": None,
                "year": None,
                "metadata_provider": "local-labelled-text",
            }
            fields = [("title", "Title"), ("authors", "Authors"), ("journal", "Journal"), ("year", "Year")]
            for field, label in fields:
                found = re.search(rf"(?im)^\s*{label}\s*:\s*([^\r\n]+)", doc["text"])
                if found:
                    value = found[1].strip()
                    if field == "authors":
                        value = [x.strip() for x in value.split(";") if x.strip()]
                    elif field == "year":
                        value = int(value) if re.fullmatch(r"\d{4}", value) else None
                    row[field] = value
        records.append({**row, "source_id": doc["source_id"]})
    return NodeResult(table=pd.DataFrame(records), data={"records": deepcopy(records), "provider": provider})


def _regex_claims(docs, cfg):
    try:
        import regex
    except ImportError:
        raise ValueError("regex extraction requires optional regex package for execution timeouts") from None
    patterns = cfg.get("patterns")
    if not isinstance(patterns, dict) or not patterns:
        raise ValueError("regex extraction requires config.patterns mapping property to pattern")
    compiled = {}
    for name, pattern in patterns.items():
        if not isinstance(pattern, str) or len(pattern) > 2000:
            raise ValueError("Unsupported regex: pattern must be a string of at most 2000 characters")
        # Reject a common dangerous form early; timeout also protects other ambiguous expressions.
        if re.search(r"\([^)]*[+*][^)]*\)[+*{]", pattern):
            raise ValueError("unsafe nested regex repetition")
        try:
            compiled[name] = regex.compile(pattern)
        except regex.error:
            raise ValueError("Unsupported regex syntax") from None
    output = []
    for doc in docs:
        for name, pattern in compiled.items():
            try:
                for match in pattern.finditer(doc["text"], timeout=0.2):
                    if match.end() == match.start():
                        continue
                    groups = match.groupdict()
                    value = groups.get("value", match.group())
                    try:
                        value = float(value)
                    except (TypeError, ValueError):
                        pass
                    if isinstance(value, float) and not math.isfinite(value):
                        raise ValueError("extracted numeric values must be finite")
                    output.append(
                        {
                            "property": name,
                            "value": value,
                            "unit": groups.get("unit"),
                            **{k: v for k, v in groups.items() if k not in {"value", "unit"}},
                            **evidence(doc, match.start(), match.end()),
                        }
                    )
            except TimeoutError:
                raise ValueError("unsafe regex exceeded the 0.2 second execution limit") from None
    return output


def extract(table=None, *, config=None, data=None, tables=None):
    cfg = config or {}
    docs = documents(table, data)
    method = cfg.get("method", "regex")
    if method == "regex":
        records = _regex_claims(docs, cfg)
    elif method == "lexicon":
        lexicon = cfg.get("lexicon", {})
        if not isinstance(lexicon, dict) or not lexicon:
            raise ValueError("lexicon must map property names to nonempty term lists")
        records = []
        for field, terms in lexicon.items():
            if not isinstance(terms, list) or not all(isinstance(t, str) and t for t in terms):
                raise ValueError("lexicon entries must be nonempty strings")
            for doc in docs:
                for term in terms:
                    for match in re.finditer(re.escape(term), doc["text"], re.I):
                        records.append(
                            {
                                "property": field,
                                "value": match.group(),
                                "unit": None,
                                **evidence(doc, match.start(), match.end()),
                            }
                        )
    elif method == "table":
        delimiter = cfg.get("delimiter", ",")
        if not isinstance(delimiter, str) or len(delimiter) != 1:
            raise ValueError("delimiter must be a single character")
        records = []
        for doc in docs:
            lines = doc["text"].splitlines(keepends=True)
            if not lines:
                continue
            parsed = list(csv.reader(io.StringIO(doc["text"]), delimiter=delimiter))
            if any("\n" in cell or "\r" in cell for row in parsed for cell in row):
                raise ValueError("table extraction requires one physical line per row")
            header, offset = parsed[0], len(lines[0])
            if len(set(header)) != len(header):
                raise ValueError("table header names must be unique")
            for index, row in enumerate(parsed[1:], 1):
                if len(row) != len(header):
                    raise ValueError("table row width does not match header")
                content = lines[index].rstrip("\r\n")
                records.append(
                    {**dict(zip(header, row, strict=True)), **evidence(doc, offset, offset + len(content))}
                )
                offset += len(lines[index])
    elif method == "llm":
        records = llm_claims(docs, cfg, "Extract reported material properties.")
    else:
        raise ValueError("method must be regex, lexicon, table, or llm")
    return NodeResult(
        table=pd.DataFrame(records), data={"records": deepcopy(records), "documents": docs, "method": method}
    )


def compare(table=None, *, config=None, data=None, tables=None):
    import pint

    cfg = config or {}
    if table is None:
        table = pd.DataFrame((data or {}).get("records", []))
    columns = ["material", "preparation", "test_condition", "property", "value", "unit", "source_id"]
    frame = require_table(table, columns)
    units = cfg.get("target_units", {})
    if not isinstance(units, dict):
        raise ValueError("target_units must map properties to explicit units")
    registry = pint.UnitRegistry()
    norm, declared = [], []
    for row in frame.to_dict("records"):
        unit = row["unit"]
        if not isinstance(unit, str) or not unit:
            raise ValueError("comparison requires explicit units for each measurement")
        try:
            value = float(row["value"])
            if not math.isfinite(value):
                raise ValueError("nonfinite value")
            target = units.get(row["property"], unit)
            norm.append(registry.Quantity(value, unit).to(target).magnitude)
            declared.append(target)
        except (ValueError, TypeError, pint.PintError):
            raise ValueError("invalid value, unit, or incompatible unit dimension in comparison") from None
    frame["normalized_value"], frame["normalized_unit"] = norm, declared
    group_columns = ["material", "preparation", "test_condition", "property", "normalized_unit"]
    # Missing material/condition cannot establish alignment: keep such rows isolated.
    groups, ids = {}, []
    for index, row in enumerate(frame.to_dict("records")):
        missing = any(pd.isna(row[c]) or str(row[c]).strip() == "" for c in group_columns)
        key = tuple(str(row[c]) for c in group_columns) + ((f"unknown-{index}",) if missing else ())
        groups.setdefault(key, len(groups) + 1)
        ids.append(groups[key])
    frame["group_id"] = ids
    conflicts = []
    tolerance = float(cfg.get("relative_tolerance", 0))
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("relative_tolerance must be finite and nonnegative")
    for group_id, group in frame.groupby("group_id", sort=False):
        values = group.normalized_value.to_numpy()
        if len(values) > 1 and max(values) - min(values) > tolerance * max(abs(values).max(), 1e-15):
            conflicts.append(
                {
                    "group_id": int(group_id),
                    "source_ids": group.source_id.tolist(),
                    "values": values.tolist(),
                    "unit": group.normalized_unit.iloc[0],
                    "interpretation": "values differ; uncertainty/significance not established",
                }
            )
    return NodeResult(
        table=frame,
        data={
            "conflicts": conflicts,
            "alignment_fields": group_columns,
            "target_units": deepcopy(units),
            "records": frame.to_dict("records"),
        },
        warnings=["Different or missing test conditions remain in separate comparison groups."],
    )


def sources(table=None, *, config=None, data=None, tables=None):
    cfg = config or {}
    docs = documents(table, data)
    original_docs = deepcopy(docs)
    if isinstance(data, dict) and data.get("records") and data.get("documents"):
        by_id = {d["source_id"]: d for d in docs}
        claims = []
        for record in data["records"]:
            if record.get("source_id") not in by_id:
                raise ValueError("source registry record has unknown source_id")
            source = by_id[record["source_id"]]
            for field in ("text", *LOCATION_FIELDS):
                if field in record and (field not in source or record[field] != source[field]):
                    raise ValueError(f"source registry record conflicts with source provenance: {field}")
            # Only the claim's excerpt selector is allowed to refine a source.
            claims.append(
                {
                    **source,
                    **{
                        field: record[field]
                        for field in ("quote", "span_start", "span_end")
                        if field in record
                    },
                }
            )
        docs = claims
    records = []
    for doc in docs:
        if "quote" in doc:
            quote = doc["quote"]
            if not isinstance(quote, str) or not quote:
                raise ValueError("source quote must be a nonempty string")
            start = doc.get("span_start", doc["text"].find(quote))
            if type(start) is not int:
                raise ValueError("source quote/span requires integer indices")
            end = doc.get("span_end", start + len(quote))
            if (
                type(end) is not int
                or not 0 <= start < end <= len(doc["text"])
                or doc["text"][start:end] != quote
            ):
                raise ValueError("source quote/span must match source text")
        else:
            start, end = 0, len(doc["text"])
        row = evidence(doc, start, end)
        row["citation"] = citation(row)
        records.append(row)
    result = NodeResult(
        table=pd.DataFrame(records), data={"sources": deepcopy(records), "documents": original_docs}
    )
    if cfg.get("save", False):
        path = artifact_path(cfg, "literature-sources.json")
        path.write_text(json.dumps(result.data, ensure_ascii=False, indent=2), encoding="utf-8")
        result.artifacts.append(str(path))
    return result


def summary(table=None, *, config=None, data=None, tables=None):
    cfg = config or {}
    docs = documents(table, data)
    question = cfg.get("question", "")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("summary requires a question for evidence retrieval")
    top_k = cfg.get("top_k", 5)
    if type(top_k) is not int or not 1 <= top_k <= 100:
        raise ValueError("top_k must be in [1, 100]")
    tokens = set(re.findall(r"\w+", question.casefold()))
    candidates = []
    for doc in docs:
        # Preserve original character offsets; sentence splitting does not reflow source text.
        for match in re.finditer(r".+?(?:[.!?](?=\s|$)|\n|$)", doc["text"], re.DOTALL):
            start, end = match.span()
            while start < end and doc["text"][start].isspace():
                start += 1
            quote = doc["text"][start:end]
            score = sum(1 for token in tokens if token in quote.casefold())
            if score:
                candidates.append((score, evidence(doc, start, end)))
    ranked = sorted(candidates, key=lambda x: -x[0])[:top_k]
    points = [x[1] for x in ranked]
    method = cfg.get("method", "extractive")
    if method == "llm" and points:
        # Send full retrieved source segments so spans still refer to the original source.
        wanted = {p["source_id"] for p in points}
        selected = [d for d in docs if d["source_id"] in wanted]
        points = llm_claims(selected, cfg, "Select evidence-supported properties relevant to: " + question)
    elif method not in {"extractive", "llm"}:
        raise ValueError("summary method must be extractive or llm")
    for point in points:
        point["citation"] = citation(point)
    text = "\n".join(f"- {p['quote']} [{p['citation']}]" for p in points)
    return NodeResult(
        table=pd.DataFrame(points),
        data={
            "summary": text,
            "points": points,
            "question": question,
            "method": method,
            "retrieval": "token-overlap-ranked-excerpts",
        },
        warnings=[] if points else ["No source excerpt matched the retrieval question."],
    )


CATALOG = [
    {
        "key": f"lit.{key}",
        "title": title,
        "function": f"{__name__}:{key}",
        "category": "literature",
        "requirement": requirement,
        "table_input": True,
        "data_input": True,
        "tables_input": False,
        "default_config": default,
    }
    for key, title, requirement, default in [
        ("search", "文献搜索", "文献搜索", {"provider": "local", "method": "keyword", "query": "ZnO"}),
        ("metadata", "文献元数据提取", "文献元数据提取", {"provider": "local"}),
        (
            "extract",
            "材料与性能信息提取",
            "材料与性能信息提取",
            {"method": "regex", "patterns": {"strength": r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>MPa|GPa)"}},
        ),
        ("compare", "多篇文献对比", "多篇文献对比", {"target_units": {}}),
        ("sources", "引文与来源记录", "引文与来源记录", {"save": False}),
        ("summary", "文献综述摘要", "文献综述摘要", {"question": "strength", "top_k": 5}),
    ]
]
