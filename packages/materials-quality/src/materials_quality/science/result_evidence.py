"""Bind computed result cells to claims without inferring physical mechanisms."""

import hashlib
import json
import math
from copy import deepcopy

import numpy as np
import pandas as pd

from materials_quality.common import json_value

from .contracts import NodeResult, require_table


def _cell(value):
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (float, np.floating)) and not math.isfinite(value):
        return None
    return json_value(value)


def result_evidence(table=None, *, config=None, data=None, tables=None):
    """Observation references are verified cells; explanation transfer stays unverified."""
    c = dict(config or {})
    frame = require_table(table, min_rows=0)
    columns = c.get("columns") or list(frame.select_dtypes(include="number").columns)
    if not isinstance(columns, list) or not columns or any(col not in frame for col in columns):
        raise ValueError("columns must select existing result columns")
    if len(set(columns)) != len(columns):
        raise ValueError("columns must not contain duplicates")
    limit = c.get("max_rows", 20)
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("max_rows must be an integer from 1 to 200")
    identity = c.get("identity_column")
    if identity and identity not in frame:
        raise ValueError("identity_column must exist in the result table")
    units = frame.attrs.get("units", {})
    snapshot = {
        "columns": list(frame.columns),
        "rows": [[_cell(v) for v in row] for row in frame.itertuples(index=False, name=None)],
        "units": json_value(units),
    }
    digest = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()
    claims = []
    for position, row in enumerate(snapshot["rows"][:limit]):
        label = row[frame.columns.get_loc(identity)] if identity else position
        for col in columns:
            value = row[frame.columns.get_loc(col)]
            unit = str(units.get(col, "unspecified"))
            claims.append(
                {
                    "claim_id": f"observation-{position + 1}-{len(claims) + 1}",
                    "kind": "observation",
                    "text": f"{label}: {col} = {value if value is not None else '未测得'} ({unit})",
                    "status": "cell_verified" if value is not None else "missing_measurement",
                    "result_ref": {
                        "table_sha256": digest,
                        "row_position": position,
                        "row_identity": label,
                        "column": col,
                        "value": value,
                        "unit": unit,
                    },
                    "meaning": "Computed table cell; not independent validation of the measurement or model.",
                }
            )
    explanation = c.get("explanation", "")
    card_id = c.get("method_card")
    sources = []
    if explanation or card_id:
        from .method_cards import load_cards

        card = next((item for item in load_cards() if item["id"] == card_id), None)
        if card is None:
            raise ValueError("method_card must select a known source-backed method card")
        sources.append({"method_id": card_id, **deepcopy(card["source"])})
        if explanation:
            claims.append(
                {
                    "claim_id": "literature-explanation",
                    "kind": "literature_explanation",
                    "text": str(explanation),
                    "status": "transfer_requires_review",
                    "source_ref": card_id,
                    "meaning": (
                        "User interpretation linked to method literature; semantic support is not verified."
                    ),
                }
            )
    if c.get("hypothesis"):
        claims.append(
            {
                "claim_id": "hypothesis",
                "kind": "hypothesis",
                "text": str(c["hypothesis"]),
                "status": "requires_experiment",
                "meaning": "Requires a discriminating experiment or control.",
            }
        )
    bundle = {
        "schema": "studyui-evidence-bundle/1",
        "table_sha256": digest,
        "row_count": len(frame),
        "included_rows": min(len(frame), limit),
        "omitted_rows": max(0, len(frame) - limit),
        "selected_columns": columns,
        "claims": claims,
        "sources": sources,
        "input_provenance": json_value(deepcopy(frame.attrs)),
        "upstream_execution": json_value(deepcopy((data or {}).get("upstream_execution"))),
        "analysis_details": json_value(
            {
                key: deepcopy(data[key])
                for key in ("method", "transform", "peak_detection", "metrics", "config")
                if isinstance(data, dict) and key in data
            }
        ),
        "scientific_validation": "not_established_by_citation_or_cell_link",
    }
    warnings = []
    if bundle["omitted_rows"]:
        warnings.append(
            f"显示前 {limit} 行；其余 {bundle['omitted_rows']} 行未生成结论卡，完整表指纹已保留。"
        )
    if explanation:
        warnings.append("文献解释由使用者提供；已关联来源，尚未验证其对当前样品的适用性。")
    summary = pd.DataFrame(
        [{k: claim.get(k) for k in ["claim_id", "kind", "text", "status"]} for claim in claims],
        columns=["claim_id", "kind", "text", "status"],
    )
    return NodeResult(
        table=summary,
        data={
            "title": c.get("title", "结果与文献证据"),
            "evidence_bundle": bundle,
            "sources": sources,
            "parameters": {"columns": columns, "max_rows": limit},
            "results": {"table_sha256": digest, "row_count": len(frame)},
            "warnings": warnings,
        },
        warnings=warnings,
    )


CATALOG = [
    {
        "key": "lit.result_evidence",
        "title": "结果与文献证据",
        "function": "materials_quality.science.result_evidence:result_evidence",
        "category": "文献与证据",
        "requirement": "结果与来源关联",
        "default_config": {"max_rows": 20},
        "table_input": True,
        "data_input": False,
        "tables_input": False,
    }
]
