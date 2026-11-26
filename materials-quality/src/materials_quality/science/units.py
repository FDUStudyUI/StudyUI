"""Normalize common unit aliases before scientific validation."""

from __future__ import annotations

_ALIASES: dict[str, dict[str, str]] = {
    "temperature": {
        "degc": "degC",
        "°c": "degC",
        "c": "degC",
        "celsius": "degC",
        "k": "K",
        "kelvin": "K",
    },
    "time": {
        "s": "s",
        "sec": "s",
        "second": "s",
        "seconds": "s",
        "min": "min",
        "minute": "min",
        "minutes": "min",
    },
    "strain": {
        "fraction": "fraction",
        "frac": "fraction",
        "1": "fraction",
        "%": "%",
        "percent": "%",
        "pct": "%",
    },
    "stress": {
        "pa": "Pa",
        "kpa": "kPa",
        "mpa": "MPa",
        "gpa": "GPa",
    },
    "angle": {
        "deg": "deg",
        "degree": "deg",
        "degrees": "deg",
        "°": "deg",
        "2theta": "deg",
        "theta": "deg",
        "rad": "rad",
        "radian": "rad",
        "radians": "rad",
    },
}


def normalize_unit_label(value, kind: str) -> str:
    """Return the canonical label for a known alias, else the stripped original."""
    text = str(value or "").strip()
    key = text.casefold().replace(" ", "")
    return _ALIASES.get(kind, {}).get(key, text)
