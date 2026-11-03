"""Keep pandas metadata and editable selections across LFX frontend serialization."""

from copy import deepcopy

from lfx.schema import DataFrame


def native_frame(frame):
    result = DataFrame(frame.copy(deep=True))
    result.attrs = deepcopy(frame.attrs)
    return result


def prepare_form(frontend_node):
    template = frontend_node.get("data", {}).get("node", frontend_node).get("template", {})
    for field in template.values():
        if not isinstance(field, dict) or not field.get("combobox") or "options" not in field:
            continue
        value = field.get("value")
        values = value if isinstance(value, list) else [value]
        for selected in values:
            if selected is not None and selected != "" and selected not in field["options"]:
                field["options"].append(selected)
    return frontend_node
