"""Run with Python after installing this package's science extra; all values are synthetic."""

import json
from pathlib import Path

from materials_quality.science import literature as lit


def main():
    output = Path(__file__).parent / "literature_output"
    docs = {
        "documents": [
            {
                "source_id": "synthetic-a",
                "page": 2,
                "table_id": "T1",
                "text": "ZnO grown by sputtering at 300 K has strength 100 MPa.",
            },
            {
                "source_id": "synthetic-b",
                "page": 3,
                "figure_id": "F1",
                "text": "ZnO grown by sputtering at 300 K has strength 0.12 GPa.",
            },
        ]
    }
    pattern = (
        r"(?P<material>ZnO) grown by (?P<preparation>sputtering) at "
        r"(?P<test_condition>300 K) has strength (?P<value>\d+(?:\.\d+)?) (?P<unit>MPa|GPa)"
    )
    discovered = lit.search(data=docs, config={"method": "boolean", "query": "ZnO AND NOT GaN"})
    extracted = lit.extract(data=docs, config={"method": "regex", "patterns": {"strength": pattern}})
    compared = lit.compare(extracted.table, config={"target_units": {"strength": "MPa"}})
    registry = lit.sources(data=extracted.data, config={"save": True, "output_dir": str(output)})
    review = lit.summary(data=registry.data, config={"question": "strength", "top_k": 2})
    local_meta = lit.metadata(
        config={"provider": "local"},
        data={
            "documents": [
                {
                    "source_id": "synthetic-meta",
                    "text": "Title: Synthetic ZnO\nAuthors: A Li; B Wu\nYear: 2024",
                }
            ]
        },
    )
    results = {
        "synthetic": True,
        "discovered": len(discovered.table),
        "metadata": local_meta.data["records"],
        "comparison": compared.table.to_dict("records"),
        "conflicts": compared.data["conflicts"],
        "review": review.data,
        "registry": registry.artifacts,
    }
    target = output / "literature-demo.json"
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    readback = json.loads(target.read_text(encoding="utf-8"))
    assert [r["normalized_value"] for r in readback["comparison"]] == [100.0, 120.0]
    assert len(readback["conflicts"]) == 1
    assert all(p["source_id"].startswith("synthetic-") for p in readback["review"]["points"])
    print(f"Verified synthetic literature workflow: {target.resolve()}")


if __name__ == "__main__":
    main()
