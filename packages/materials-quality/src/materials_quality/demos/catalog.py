"""Fixed dataset identities; no caller-supplied filesystem paths."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def list_datasets():
    """Return fresh public records, including provenance and scope boundaries."""
    return json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))


def get_dataset(dataset_id):
    if not isinstance(dataset_id, str):
        raise ValueError("Unknown demonstration dataset")
    for item in list_datasets():
        if item["id"] == dataset_id:
            return item
    raise ValueError(f"Unknown demonstration dataset: {dataset_id}")


def read_demo_bytes(dataset_id):
    """Read the packaged original and fail closed if its SHA-256 changed."""
    item = get_dataset(dataset_id)
    raw = (ROOT / "data" / item["filename"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != item["sha256"]:
        raise ValueError(f"Demonstration source checksum mismatch: {dataset_id}")
    return raw
