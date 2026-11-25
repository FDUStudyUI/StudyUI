"""Run all 12 example nodes; verify raw hashes and read back every artifact."""

import argparse
import hashlib
import importlib
import json
from pathlib import Path

import pandas as pd
from PIL import Image

from materials_quality.science.extract_nodes import CATALOG as EXTRACT
from materials_quality.science.io_nodes import CATALOG as IO


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="artifacts/io-demo")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    configs = json.loads((root / "configs.json").read_text(encoding="utf-8"))
    before = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (root / "fixtures").iterdir()
    }
    summary = []
    for entry in IO + EXTRACT:
        module, name = entry["function"].split(":")
        operation = getattr(importlib.import_module(module), name)
        config = configs[entry["key"]]
        config["output_dir"] = str(Path(args.output_dir).resolve() / entry["key"].replace(".", "-"))
        result = operation(config=config)
        readbacks = []
        for artifact in result.artifacts:
            path = Path(artifact)
            if path.suffix == ".png":
                with Image.open(path) as image:
                    image.load()
                    readbacks.append({"path": str(path), "size": list(image.size)})
            elif path.suffix == ".csv":
                readbacks.append({"path": str(path), "rows": len(pd.read_csv(path))})
            else:
                readbacks.append({"path": str(path), "bytes": len(path.read_bytes())})
        summary.append(
            {
                "key": entry["key"],
                "rows": len(result.table) if result.table is not None else None,
                "warnings": result.warnings,
                "artifacts_read_back": readbacks,
            }
        )
    after = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (root / "fixtures").iterdir()
    }
    if before != after:
        raise AssertionError("a synthetic raw fixture changed")
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "verification.json").write_text(
        json.dumps({"raw_hashes_unchanged": True, "operations": summary}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "operations": len(summary),
                "raw_hashes_unchanged": True,
                "verification": str(output / "verification.json"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
