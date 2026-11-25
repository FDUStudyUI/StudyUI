"""Deterministic, synthetic evidence checks for all six literature nodes."""

import importlib.util

import pandas as pd
import pytest


def lit():
    assert importlib.util.find_spec("materials_quality.science.literature"), "literature operations required"
    from materials_quality.science import literature

    return literature


DOCS = {
    "documents": [
        {
            "source_id": "a",
            "doi": "10.1234/a",
            "page": 2,
            "table_id": "T1",
            "text": "ZnO was grown by sputtering. At 300 K, strength was 100 MPa.",
        },
        {
            "source_id": "b",
            "doi": "10.1234/b",
            "page": 4,
            "text": "ZnO was grown by sputtering. At 300 K, strength was 0.12 GPa.",
        },
    ]
}


def test_catalog_and_local_boolean_author_doi_search():
    module = lit()
    assert {x["key"] for x in module.CATALOG} == {
        "lit.search",
        "lit.metadata",
        "lit.extract",
        "lit.compare",
        "lit.sources",
        "lit.summary",
    }
    records = [
        {"title": "ZnO flexible sensor", "authors": ["A Li"], "doi": "10.1234/a"},
        {"title": "ZnO rigid sensor", "authors": ["B Wu"], "doi": "10.1234/b"},
        {"title": "GaN flexible detector", "authors": ["A Li"], "doi": "10.1234/c"},
    ]
    for method, query, expected in [
        ("boolean", '(ZnO AND "flexible sensor") OR (GaN AND NOT rigid)', ["10.1234/a", "10.1234/c"]),
        ("author", "A Li", ["10.1234/a", "10.1234/c"]),
        ("doi", "https://doi.org/10.1234/b", ["10.1234/b"]),
        ("keyword", "ZnO sensor", ["10.1234/a", "10.1234/b"]),
    ]:
        result = module.search(
            config={"provider": "local", "method": method, "query": query}, data={"records": records}
        )
        assert result.table.doi.tolist() == expected
    with pytest.raises(ValueError, match="Boolean"):
        module.search(
            config={"provider": "local", "method": "boolean", "query": "ZnO AND ("}, data={"records": records}
        )


def test_metadata_doi_text_local_never_invents_absent_fields():
    result = lit().metadata(
        data={
            "documents": [
                {
                    "source_id": "x",
                    "text": "Title: Synthetic sensor\nAuthors: Li; Wu\nJournal: Test Journal\nYear: 2024\n"
                    "https://doi.org/10.1234/ABC.",
                }
            ]
        },
        config={"provider": "local"},
    )
    assert result.table.iloc[0]["doi"] == "10.1234/abc"
    assert result.table.iloc[0]["authors"] == ["Li", "Wu"]
    missing = (
        lit()
        .metadata(
            data={"documents": [{"source_id": "y", "text": "unlabelled paragraph"}]},
            config={"provider": "local"},
        )
        .table.iloc[0]
    )
    assert missing["title"] is None and missing["year"] is None


def test_regex_lexicon_table_extraction_retains_exact_locations():
    rules = {"strength": r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>MPa|GPa)"}
    result = lit().extract(data=DOCS, config={"method": "regex", "patterns": rules})
    assert result.table.value.tolist() == [100.0, 0.12]
    for row in result.table.to_dict("records"):
        doc = next(d for d in DOCS["documents"] if d["source_id"] == row["source_id"])
        assert doc["text"][row["span_start"] : row["span_end"]] == row["quote"]
        assert row["page"] == doc["page"]
    lexical = lit().extract(data=DOCS, config={"method": "lexicon", "lexicon": {"material": ["ZnO"]}})
    assert lexical.table["value"].tolist() == ["ZnO", "ZnO"]
    text = "material,strength,unit\nZnO,100,MPa\nGaN,200,MPa"
    tabular = lit().extract(
        data={"documents": [{"source_id": "t", "text": text, "table_id": "T2"}]},
        config={"method": "table", "delimiter": ","},
    )
    assert tabular.table.iloc[0]["strength"] == "100"
    assert tabular.table.iloc[0]["quote"] == "ZnO,100,MPa"
    with pytest.raises(ValueError, match="unsafe|Unsupported"):
        lit().extract(data=DOCS, config={"patterns": {"bad": "(a+)+$"}})


def test_compare_explicit_units_conditions_and_conflicts():
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
            },
            {
                "material": "ZnO",
                "preparation": "sputtering",
                "test_condition": "300 K",
                "property": "strength",
                "value": 0.12,
                "unit": "GPa",
                "source_id": "b",
            },
            {
                "material": "ZnO",
                "preparation": "sputtering",
                "test_condition": "400 K",
                "property": "strength",
                "value": 90,
                "unit": "MPa",
                "source_id": "c",
            },
        ]
    )
    original = frame.copy(deep=True)
    result = lit().compare(frame, config={"target_units": {"strength": "MPa"}})
    assert result.table.normalized_value.tolist() == [100, 120, 90]
    assert result.table.group_id.iloc[0] == result.table.group_id.iloc[1]
    assert result.table.group_id.iloc[0] != result.table.group_id.iloc[2]
    assert len(result.data["conflicts"]) == 1
    pd.testing.assert_frame_equal(original, frame)
    with pytest.raises(ValueError, match="unit|dimension"):
        lit().compare(frame, config={"target_units": {"strength": "second"}})


def test_sources_and_retrieval_summary_support_pdf_text_rows():
    frame = pd.DataFrame(
        [
            {
                "page": 2,
                "text": "ZnO strength is 100 MPa.",
                "source_file": "paper.pdf",
                "bbox": [0, 0, 100, 40],
                "confidence": 1.0,
            }
        ]
    )
    registered = lit().sources(frame)
    source = registered.table.iloc[0]
    assert source["page"] == 2 and source["source_file"] == "paper.pdf"
    result = lit().summary(data=DOCS, config={"question": "strength", "top_k": 1})
    assert len(result.data["points"]) == 1
    point = result.data["points"][0]
    assert point["quote"] == DOCS["documents"][0]["text"][point["span_start"] : point["span_end"]]
    assert "10.1234/a" in point["citation"] and "page 2" in point["citation"]
    assert point["quote"] in result.data["summary"]
    empty = lit().summary(data=DOCS, config={"question": "unobtainium"})
    assert empty.data["points"] == [] and empty.warnings


def test_summary_preserves_decimal_and_claim_registry_roundtrip(tmp_path):
    docs = {"documents": [{"source_id": "x", "text": "ZnO strength is 0.12 GPa.", "figure_id": "F2"}]}
    result = lit().summary(data=docs, config={"question": "strength"})
    assert result.data["points"][0]["quote"] == docs["documents"][0]["text"]
    extracted = lit().extract(data=docs, config={"patterns": {"strength": r"(?P<value>0\.12) (?P<unit>GPa)"}})
    registered = lit().sources(data=extracted.data, config={"save": True, "output_dir": str(tmp_path)})
    assert registered.table.iloc[0]["quote"] == "0.12 GPa"
    assert registered.table.iloc[0]["figure_id"] == "F2"
    import json
    from pathlib import Path

    saved = json.loads(Path(registered.artifacts[0]).read_text(encoding="utf-8"))
    assert saved["sources"][0]["quote"] == "0.12 GPa"


def test_document_search_and_multi_claim_registry_can_feed_summary():
    result = lit().search(data=DOCS, config={"provider": "local", "query": "strength"})
    assert len(result.table) == 2
    extracted = lit().extract(
        data=DOCS,
        config={"method": "lexicon", "lexicon": {"material": ["ZnO"], "preparation": ["sputtering"]}},
    )
    registered = lit().sources(data=extracted.data)
    assert len(registered.table) == 4
    assert len(registered.data["documents"]) == 2
    assert lit().summary(data=registered.data, config={"question": "strength"}).data["points"]


def test_missing_conditions_remain_unaligned_and_temperatures_are_affine():
    frame = pd.DataFrame(
        [
            {
                "material": "ZnO",
                "preparation": None,
                "test_condition": "ambient",
                "property": "temperature",
                "value": 0,
                "unit": "degC",
                "source_id": "a",
            },
            {
                "material": "ZnO",
                "preparation": None,
                "test_condition": "ambient",
                "property": "temperature",
                "value": 273.15,
                "unit": "kelvin",
                "source_id": "b",
            },
        ]
    )
    result = lit().compare(frame, config={"target_units": {"temperature": "kelvin"}})
    assert result.table.normalized_value.tolist() == [273.15, 273.15]
    assert result.table.group_id.nunique() == 2
