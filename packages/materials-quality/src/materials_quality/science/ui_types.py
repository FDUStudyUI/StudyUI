"""Declarative, JSON-safe UI fields; no scientific or platform imports."""

from copy import deepcopy

KINDS = {"str", "list", "int", "float", "bool", "choice", "dict", "range", "table", "json"}


def field(
    path,
    label,
    kind="str",
    *,
    default=None,
    choices=(),
    advanced=False,
    info="",
    when=None,
    required=False,
    **extra,
):
    if kind not in KINDS or not isinstance(path, str) or not path:
        raise ValueError(f"Invalid field descriptor: {path!r}/{kind!r}")
    return deepcopy(
        {
            "path": path,
            "label": label,
            "kind": kind,
            "default": default,
            "choices": list(choices),
            "advanced": advanced,
            "info": info,
            "when": when or {},
            "required": required,
            **extra,
        }
    )


def input_name(path):
    return "cfg_" + path.replace(".", "_")
