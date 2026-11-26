"""Build StudyUI's MatOS tool catalog from a read-only MatOS checkout.

The generator only reads MatOS ``asset.json`` / ``input.schema.json`` /
``prompt.md`` files. It never imports, installs or executes MatOS code.

Usage::

    python -m scripts.build_matos_catalog --matos-root /path/to/MatOS \
        --commit <matos-commit>

MatOS is licensed under PolyForm Noncommercial 1.0.0; its required notice is
recorded in the generated catalog and in ``THIRD_PARTY_NOTICES.md``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PACK_ROOT = "distribution/benchmark-minimal/assets/packs"
CATALOG_VERSION = 1
REPOSITORY = "https://github.com/DingyangLyu/MatOS"
LICENSE = "PolyForm Noncommercial License 1.0.0"
LICENSE_URL = "https://polyformproject.org/licenses/noncommercial/1.0.0/"
REQUIRED_NOTICE = "Required Notice: Copyright 2026 The MatOS Authors (https://github.com/DingyangLyu/MatOS)"
INSTALL_HINT = (
    "Install MatOS and expose its `matos` CLI on PATH, or set "
    "STUDYUI_MATOS_CLI=/path/to/matos. StudyUI never vendors or executes the "
    "downloaded MatOS source tree."
)

# Per-tool runtime facts that are not expressible in the upstream asset.json.
# ``required_*`` entries block execution; ``probed_*`` entries are optional
# capability probes that the catalog tool reports on but does not require.
TOOL_RUNTIME: dict[str, dict[str, object]] = {
    "atomistic-toolchain-catalog": {
        "probed_binaries": [
            "xtb",
            "crest",
            "gromacs",
            "openmm",
            "plumed",
            "abacus",
            "cp2k",
            "pw.x",
            "wannier90.x",
            "yambo",
            "qmcpack",
        ],
        "notes": "Read-only discovery and probe of mounted atomistic solvers.",
    },
    "battery-electrochem-catalog": {
        "probed_python_packages": ["pybamm", "pybop", "bpx", "liionpack", "openpnm"],
        "notes": "Read-only discovery of mounted battery/electrochemistry packages.",
    },
    "conda-environment-catalog": {
        "required_binaries": ["conda"],
        "notes": "Read-only Conda environment inventory.",
    },
    "conda-environment-manager": {
        "required_binaries": ["conda", "pip"],
        "notes": "Creates current-user Conda environments; never writes shared/system environments.",
    },
    "document-parse": {
        "optional_binaries": ["pdftotext", "libreoffice"],
        "probed_python_packages": ["fitz", "pypdf", "docx", "bs4"],
        "notes": "PDF/DOCX/HTML text extraction with Python fallbacks.",
    },
    "gemini-vision-analyze": {
        "required_env": ["GEMINI_API_KEY"],
        "notes": "Calls a Gemini-compatible vision endpoint; network access required.",
    },
    "literature-access": {
        "notes": "Credential-safe local-library scan and legal open-access DOI resolution.",
    },
    "local-toolchain-preflight": {
        "probed_binaries": [
            "vasp_std",
            "pw.x",
            "lmp",
            "blockMesh",
            "icoFoam",
            "elk",
            "wannier90.x",
            "orca",
            "scip",
            "conda",
            "python3",
        ],
        "probed_python_packages": ["thermocalc", "pyscipopt"],
        "notes": "Read-only preflight; never runs production calculations.",
    },
    "materials-runtime-inventory": {
        "probed_binaries": ["conda", "python3"],
        "notes": "Aggregates toolchain, Conda, MLIP and pseudopotential catalogs.",
    },
    "mlip-model-catalog": {
        "probed_python_packages": [
            "mace",
            "chgnet",
            "matgl",
            "sevenn",
            "orb_models",
            "mattersim",
            "fairchem",
            "nequip",
            "torch_sim",
        ],
        "notes": "Read-only inventory of mounted machine-learning interatomic potentials.",
    },
    "mp-query": {
        "required_env": ["MP_API_KEY"],
        "notes": "Read-only Materials Project REST query; network access required.",
    },
    "scip-toolchain-catalog": {
        "probed_binaries": ["scip", "soplex", "gcg"],
        "probed_python_packages": ["pyscipopt"],
        "notes": "Read-only SCIP/SoPlex/GCG discovery with optional smoke test.",
    },
    "web-read": {
        "notes": "Public URL/PDF to Markdown via Jina Reader with bounded fallbacks.",
    },
    "deep-research-search": {
        "notes": "OpenAlex scholarly search; provider-agnostic and keyless.",
    },
}

BUILTIN_RUNTIME = {
    "agent-orchestration": {
        "notes": "MatOS/DeepSeek Harness builtin sub-agent and task tools.",
    },
    "files-core": {"notes": "MatOS/DeepSeek Harness builtin workspace file tools."},
    "shell-core": {"notes": "MatOS/DeepSeek Harness builtin shell tools."},
    "web-research": {"notes": "MatOS/DeepSeek Harness builtin web search/fetch tools."},
}


def _prompt_excerpt(path: Path) -> str:
    if not path.is_file():
        return ""
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-")):
            if lines:
                break
            continue
        lines.append(line)
    text = " ".join(lines).strip()
    return text[:400]


def _tool_record(asset_path: Path) -> dict:
    asset = json.loads(asset_path.read_text(encoding="utf-8"))
    tool_id = str(asset["id"])
    metadata = asset.get("metadata") or {}
    kind = str(metadata.get("kind") or "external-tool")
    executor = metadata.get("executor") or {}
    schema_path = asset_path.parent / "input.schema.json"
    if kind == "external-tool":
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        call_method = "matos assets run-tool"
        availability = "requires_matos_cli"
        entrypoint = str(asset.get("entry") or "./tool.py")
        mcp_name = executor.get("mcpName") or metadata.get("mcpName")
        timeout_ms = int(executor.get("timeoutMs") or 60000)
    else:
        schema = {"type": "object", "additionalProperties": True}
        call_method = "matos_asset MCP server (builtin pack)"
        availability = "matos_runtime_only"
        entrypoint = ""
        mcp_name = None
        timeout_ms = None
    runtime = dict(TOOL_RUNTIME.get(tool_id) or BUILTIN_RUNTIME.get(tool_id) or {})
    permissions = asset.get("permissions") or {}
    return {
        "id": tool_id,
        "ref": f"tool:{tool_id}",
        "name": str(asset.get("name") or tool_id),
        "version": str(asset.get("version") or "0.0.0"),
        "description": str(asset.get("description") or ""),
        "kind": kind,
        "family": str(metadata.get("family") or ("builtin-pack" if kind == "builtin-pack" else "general")),
        "tags": list(asset.get("tags") or []),
        "permissions": {
            "shell": str(permissions.get("shell") or "disabled"),
            "network": str(permissions.get("network") or "disabled"),
            "workspace": str(permissions.get("workspace") or "read-only"),
            "secrets": list(permissions.get("secrets") or []),
        },
        "call_method": call_method,
        "executor": str(executor.get("type") or ("matos-builtin-pack" if kind == "builtin-pack" else "")),
        "entrypoint": entrypoint,
        "mcp_name": mcp_name,
        "timeout_ms": timeout_ms,
        "input_schema": schema,
        "builtin_tools": list(metadata.get("builtinTools") or []),
        "required_binaries": list(runtime.get("required_binaries") or []),
        "probed_binaries": list(runtime.get("probed_binaries") or []),
        "optional_binaries": list(runtime.get("optional_binaries") or []),
        "probed_python_packages": list(runtime.get("probed_python_packages") or []),
        "required_env": list(runtime.get("required_env") or []),
        "network_required": permissions.get("network") == "enabled",
        "availability": availability,
        "notes": str(runtime.get("notes") or ""),
        "usage_hint": _prompt_excerpt(asset_path.parent / "prompt.md"),
        "provenance": {
            "asset_path": str(asset_path.relative_to(asset_path.parents[3])).replace("\\", "/"),
            "asset_file": "asset.json",
            "binding": str(metadata.get("binding") or ""),
        },
    }


def build(matosc_root: Path, commit: str) -> dict:
    tools = [_tool_record(path) for path in sorted((matosc_root / PACK_ROOT).glob("**/tools/*/asset.json"))]
    tools.sort(key=lambda item: item["id"])
    external = [item["id"] for item in tools if item["kind"] == "external-tool"]
    builtin = [item["id"] for item in tools if item["kind"] == "builtin-pack"]
    return {
        "schema_version": CATALOG_VERSION,
        "source": {
            "project": "MatOS",
            "repository": REPOSITORY,
            "commit": commit,
            "snapshot_date": "2026-10-25T10:42:54Z",
            "license": LICENSE,
            "license_url": LICENSE_URL,
            "required_notice": REQUIRED_NOTICE,
            "asset_root": PACK_ROOT,
            "install_hint": INSTALL_HINT,
            "attribution": (
                "The MatOS tool names, descriptions, permissions and JSON input schemas in this "
                "catalog are adapted from the MatOS benchmark-minimal distribution. StudyUI does "
                "not bundle or execute MatOS source code; execution is delegated to a user-installed "
                "`matos` CLI and its `matos assets run-tool` JSON interface."
            ),
        },
        "summary": {
            "tool_count": len(tools),
            "external_tool_count": len(external),
            "builtin_pack_count": len(builtin),
            "external_tool_ids": external,
            "builtin_pack_ids": builtin,
        },
        "tools": tools,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matos-root", required=True, type=Path)
    parser.add_argument(
        "--commit",
        default="a50fd7613346a59f13e87a8bc368d0cec048585d",
        help="MatOS commit provenance for the generated snapshot.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "src"
        / "materials_quality"
        / "matos"
        / "catalog_data.json",
    )
    args = parser.parse_args(argv)
    payload = build(args.matos_root.expanduser().resolve(), args.commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(payload['tools'])} MatOS tools to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
