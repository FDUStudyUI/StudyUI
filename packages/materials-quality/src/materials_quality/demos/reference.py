"""Load only the stored reference graph corresponding to a catalog identity."""

import hashlib
import json

from .catalog import ROOT, get_dataset, read_demo_bytes


def load_reference_flow(dataset_id):
    """Return a fresh portable Langflow payload without executing any node."""
    item = get_dataset(dataset_id)
    read_demo_bytes(dataset_id)
    path = ROOT / "flows" / (item["id"] + ".json")
    raw = path.read_bytes()
    hashes = json.loads((ROOT / "flows" / "checksums.json").read_text(encoding="utf-8"))
    if hashlib.sha256(raw).hexdigest() != hashes.get(item["id"]):
        raise ValueError("Packaged demonstration reference checksum mismatch")
    payload = json.loads(raw)
    if payload.get("demo_dataset_id") != item["id"] or not payload.get("data", {}).get("nodes"):
        raise ValueError("Invalid packaged demonstration reference flow")
    return payload
