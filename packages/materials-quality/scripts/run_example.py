"""Reimport and execute a serialized example with the actual LFX graph runner."""

import argparse
import copy
import json
from pathlib import Path

from lfx.graph import Graph
from lfx.schema import Data

from scripts.build_example import SUMMARY_ID


def execute_payload(payload):
    graph = Graph.from_payload(copy.deepcopy(payload))
    # Consume the whole graph. Fetch its actual computed output, not a second
    # direct call to the summarizer (which would bypass graph wiring).
    for step in graph.start():
        if hasattr(step, "valid") and not step.valid:
            raise RuntimeError(f"Graph step failed: {step}")
    vertex = graph.get_vertex(SUMMARY_ID)
    report = vertex.results.get("report")
    if not isinstance(report, Data):
        raise RuntimeError(f"Graph did not produce a Data report; outputs: {list(vertex.results)}")
    return report.data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("flow", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = execute_payload(json.loads(args.flow.read_text(encoding="utf-8")))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "execution_status": report["execution_status"],
                "passed": report["passed"],
                "checks": report["metrics"],
                "total_findings": report["total_findings"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
