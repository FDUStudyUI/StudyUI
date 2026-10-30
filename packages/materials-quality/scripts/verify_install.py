"""Verify a regular wheel install, native discovery and both stored flow JSONs."""

import argparse
import json
from pathlib import Path

from lfx.custom.directory_reader.utils import build_custom_component_list_from_path
from lfx.graph import Graph
from lfx.schema import Data

import materials_quality


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-wheel", action="store_true")
    args = parser.parse_args()
    package = Path(materials_quality.__file__).resolve().parent
    if args.require_wheel and "site-packages" not in package.parts:
        raise RuntimeError(f"Expected wheel installation, got {package}")
    component_path = package / "component_sources"
    if component_path.is_dir():
        discovered = build_custom_component_list_from_path(str(component_path))
        if len(discovered.get("materials_quality", {})) != 7:
            raise RuntimeError("Installed component discovery did not find seven nodes")
    elif args.require_wheel:
        raise RuntimeError("Wheel does not contain installable component sources")
    root = Path(__file__).resolve().parents[1]
    results = {}
    for case in ("clean", "dirty"):
        payload = json.loads((root / "examples" / f"{case}_quality_flow.json").read_text(encoding="utf-8"))
        graph = Graph.from_payload(payload)
        for step in graph.start():
            if hasattr(step, "valid") and not step.valid:
                raise RuntimeError(f"{case} flow execution failed")
        report = graph.get_vertex("MaterialQualitySummary-demo").results.get("report")
        if not isinstance(report, Data) or report.data["metrics"]["completed_checks"] != 6:
            raise RuntimeError(f"{case} flow did not complete all checks")
        if report.data["passed"] != (case == "clean"):
            raise RuntimeError(f"{case} flow verdict is incorrect")
        results[case] = {"passed": report.data["passed"], "findings": report.data["total_findings"]}
    print(json.dumps({"wheel": "site-packages" in package.parts, "flows": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
