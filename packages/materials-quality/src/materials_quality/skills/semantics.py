"""Task-specific declarations and output meanings, separate from numerical values."""

from materials_quality.science.table_contract import make_contract, read_contract


def analysis_contract(table, task, parameters):
    p = parameters
    source = read_contract(table)
    issues = []
    if source is not None:
        allowed = {
            "spectra": {"point"},
            "mechanics": {"point"},
            "contrast": {"measurement", "curve", "sample", "experimental_unit"},
        }[task]
        if source["granularity"] not in allowed:
            issues.append(
                {"field": "contract", "message": "输入数据粒度不适用于此任务，请连接原始测量或正确的特征表。"}
            )
        if task == "contrast" and "x" in source["roles"]:
            issues.append(
                {"field": "contract", "message": "逐坐标曲线不能直接当作独立样品比较；请先提取每曲线特征。"}
            )
    if task == "spectra":
        roles = {
            "curve_id": p.get("curve_id"),
            "x": p.get("x"),
            "response": p.get("y"),
            "group": p.get("group"),
        }
        if p.get("unit_mode") == "curve":
            roles["experimental_unit"] = p.get("curve_id")
        elif p.get("unit_mode") == "sample":
            roles["experimental_unit"] = p.get("experimental_unit")
        design = {
            "kind": "independent" if p.get("unit_mode") != "descriptive" else "descriptive",
            "confirmed": bool(p.get("unit_confirmed")) if p.get("unit_mode") != "descriptive" else False,
        }
        grain = "point"
    elif task == "mechanics":
        roles = {
            "x": p.get("strain"),
            "response": p.get("stress"),
            "sample_id": p.get("sample_id"),
            "group": p.get("group"),
        }
        design, grain = {"kind": "descriptive", "confirmed": False}, "point"
    else:
        roles = {
            "group": p.get("group"),
            "variable": p.get("variable"),
            "response": p.get("value"),
            "sample_id": p.get("sample_id"),
            "experimental_unit": p.get("experimental_unit"),
        }
        if p.get("sample_id") != p.get("experimental_unit"):
            roles["technical_replicate"] = roles.pop("sample_id")
        design = {
            "kind": p.get("design") or "descriptive",
            "confirmed": p.get("design") in {"independent", "paired"},
        }
        grain = source["granularity"] if source else "measurement"
    roles = {k: v for k, v in roles.items() if isinstance(v, str) and v in table}
    if source is not None:
        if task == "spectra":
            for role in ("sample_id", "experimental_unit"):
                if role in source["roles"] and role not in roles:
                    roles[role] = source["roles"][role]
            if design["kind"] == "descriptive":
                design = dict(source["experimental_design"])
        for role, column in source["roles"].items():
            if role in roles and roles[role] != column:
                issues.append(
                    {"field": "contract", "message": f"{role} 与上游数据契约不一致，请核对列映射。"}
                )
        if source["experimental_design"]["confirmed"] and design["confirmed"]:
            if source["experimental_design"]["kind"] != design["kind"]:
                issues.append({"field": "contract", "message": "试验设计与上游确认的设计冲突。"})
    if issues:
        return None, issues
    try:
        contract = make_contract(
            table,
            granularity=grain,
            roles=roles,
            experimental_design=design,
            aggregation=source["aggregation"] if source else [],
            derived_from=[{"contract_sha256": source["contract_sha256"], "operation": "research_plan"}]
            if source
            else [],
            units_state={
                "source": "explicit_task_parameters",
                "units": {
                    p[column]: p[unit]
                    for column, unit in (
                        ("x", "x_unit"),
                        ("y", "y_unit"),
                        ("strain", "strain_unit"),
                        ("stress", "stress_unit"),
                        ("value", "value_unit"),
                    )
                    if column in p and unit in p and isinstance(p[column], str)
                },
            },
        )
    except ValueError as exc:
        return None, [{"field": "contract", "message": f"数据契约需要复核：{exc}"}]
    return contract, []


def output_contract(table, plan, name):
    """Declare actual row meaning; group summaries never invent independent units."""
    task, p = plan["task"], plan["parameters"]
    if not len(table.columns):
        return None
    roles, grain = {}, "group_summary"
    if name == "curves":
        grain = "point"
        roles = (
            {"sample_id": "sample_id", "x": "strain_fraction", "response": "stress_MPa", "group": "group"}
            if task == "mechanics"
            else {"curve_id": "curve_id", "x": "x", "response": "smoothed", "group": "group"}
        )
        if task == "spectra" and "experimental_unit" in table:
            roles["experimental_unit"] = "experimental_unit"
    elif task == "spectra" and name in {"table", "features"}:
        grain = "curve" if name == "table" else "peak"
        roles = {
            "curve_id": "curve_id",
            "group": "group",
            "response": "window_candidate_nm" if name == "table" else "peak_position",
        }
        if "experimental_unit" in table:
            roles["experimental_unit"] = "experimental_unit"
    elif task == "mechanics" and name in {"table", "features"}:
        grain = "sample"
        roles = {"sample_id": "sample_id", "response": "elastic_modulus_MPa", "group": "group"}
    elif task == "contrast" and name == "table":
        grain = "experimental_unit"
        roles = {
            "experimental_unit": p["experimental_unit"],
            "variable": p["variable"],
            "group": p["group"],
            "response": p["value"],
        }
    elif name == "groups":
        roles = {"group": "group", "variable": "variable", "response": "mean"}
    elif task == "contrast" and name == "features":
        roles = {"variable": "variable", "response": "mean_difference"}
    roles = {k: v for k, v in roles.items() if v in table and not (k == "group" and table[v].isna().any())}
    return make_contract(
        table,
        granularity=grain,
        roles=roles,
        experimental_design=(
            {"kind": p["design"], "confirmed": True}
            if task == "contrast" and name == "table"
            else plan["analysis_contract"]["experimental_design"]
            if task == "spectra" and "experimental_unit" in roles
            else None
        ),
        aggregation=[
            {
                "operation": f"research.{task}.{name}",
                "parameters": {"unit_mode": p.get("unit_mode", "declared_task")},
            }
        ],
        derived_from=[
            {"contract_sha256": plan["analysis_contract"]["contract_sha256"], "operation": "analysis"}
        ],
    )
