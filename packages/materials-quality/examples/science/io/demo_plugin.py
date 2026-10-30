"""Explicit converter for this repository's synthetic vendor.raw fixture only."""

import io

import pandas as pd


def convert(path, config):
    raw = path.read_bytes()
    signature = b"SYNTHETIC_VENDOR_DEMO\n"
    if not raw.startswith(signature):
        raise ValueError("demo plugin accepts only SYNTHETIC_VENDOR_DEMO fixture files")
    return pd.read_csv(io.BytesIO(raw[len(signature) :]), names=["x", "y"])
