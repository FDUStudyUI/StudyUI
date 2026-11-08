"""Regressions: missing provenance and malformed service data must stay diagnosable."""

import json
from pathlib import Path

import pandas as pd
import pytest

from materials_quality.science import literature
from materials_quality.science.lit_evidence import citation, request_json

TEXT = "ZnO strength was 100 MPa."
PATTERNS = {"strength": r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>MPa)"}


def missing_provenance_data():
    frame = pd.DataFrame([{"source_id": "a", "text": TEXT, "page": float("nan"), "confidence": float("nan")}])
    return literature.extract(frame, config={"method": "regex", "patterns": PATTERNS}).data


def test_claim_registry_roundtrip_tolerates_missing_provenance():
    registered = literature.sources(data=missing_provenance_data())
    row = registered.table.iloc[0]
    assert row["quote"] == "100 MPa"
    assert row["citation"] == "a"
    assert "page" not in registered.data["sources"][0]


def test_citation_never_renders_missing_provenance_values():
    nan = float("nan")
    assert citation({"source_id": "s1", "doi": nan, "page": nan}) == "s1"
    assert citation({"source_id": "s1", "url": nan}) == "s1"
    assert citation({"source_id": "s1", "doi": "10.1234/a", "page": nan, "table_id": nan}) == (
        "https://doi.org/10.1234/a"
    )
    assert citation({"source_id": "s1", "doi": "", "url": "", "source_file": ""}) == "s1"


def test_saved_source_registry_is_strict_json(tmp_path):
    registered = literature.sources(
        data=missing_provenance_data(), config={"save": True, "output_dir": str(tmp_path)}
    )
    text = Path(registered.artifacts[0]).read_text(encoding="utf-8")

    def refuse(token):
        raise AssertionError(f"non-finite JSON constant written: {token}")

    saved = json.loads(text, parse_constant=refuse)
    assert saved["sources"][0]["quote"] == "100 MPa"


def test_compare_rejects_null_relative_tolerance():
    frame = pd.DataFrame(
        [
            {
                "material": "ZnO",
                "preparation": "sputtering",
                "test_condition": "300 K",
                "property": "strength",
                "value": 100,
                "unit": "MPa",
                "source_id": "a",
            }
        ]
    )
    with pytest.raises(ValueError, match="relative_tolerance"):
        literature.compare(frame, config={"relative_tolerance": None})


def test_http_timeout_must_be_numeric():
    with pytest.raises(ValueError, match="timeout"):
        request_json("https://example.invalid/works", config={"timeout": None})


def test_crossref_malformed_record_is_value_error(monkeypatch):
    monkeypatch.setattr(
        literature,
        "request_json",
        lambda *args, **kwargs: {"message": {"items": [{"DOI": "10.1234/a", "published": ["1999"]}]}},
    )
    with pytest.raises(ValueError, match="Crossref"):
        literature.search(config={"provider": "crossref", "method": "keyword", "query": "ZnO"})
