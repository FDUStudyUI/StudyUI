"""Regression: LFX debug runs must expose report metrics (modulus/yield) to the agent."""

from materials_quality.agent.harness import _bounded_tool_content, _compact_run_result


def _debug_result():
    return {
        "session_id": "s1",
        "outputs": [
            {
                "outputs": [
                    {
                        "component_id": "imp",
                        "component_display_name": "材料科学·表格文件导入",
                        "outputs": {
                            "table": {"message": [{"strain": 0.0, "stress": 0.0}]},
                            "report": {"type": "object", "message": {"execution_status": "completed"}},
                        },
                    },
                    {
                        "component_id": "mech",
                        "component_display_name": "材料科学·应力—应变分析",
                        "outputs": {
                            "table": {"message": [{"strain_fraction": 0.0, "stress_MPa": 0.0}]},
                            "report": {
                                "type": "object",
                                "message": {
                                    "schema_version": 1,
                                    "operation": "materials.mechanics",
                                    "execution_status": "completed",
                                    "data": {
                                        "elastic_modulus_MPa": 200000.0,
                                        "yield_stress_MPa": 202.01005025125627,
                                        "fit_range_fraction": [0.0, 0.0008],
                                        "fracture_strain": None,
                                    },
                                    "warnings": ["The final measured strain is not a confirmed fracture"],
                                },
                            },
                            "summary": {"type": "unknown", "message": ""},
                        },
                    },
                ]
            }
        ],
    }


def test_debug_wrapped_report_metrics_reach_the_agent_tool_content():
    compact = _compact_run_result(_debug_result())
    mech = next(row for row in compact["outputs"] if row["node_id"] == "mech")
    report = mech["outputs"]["report"]
    assert report["data"]["elastic_modulus_MPa"] == 200000.0
    assert report["data"]["yield_stress_MPa"] == 202.01005025125627
    assert report["execution_status"] == "completed"
    assert report["warnings"] == ["The final measured strain is not a confirmed fracture"]

    encoded = _bounded_tool_content("run_workflow", compact)
    assert "elastic_modulus_MPa" in encoded
    assert "200000" in encoded
    assert "yield_stress_MPa" in encoded


def test_report_summary_still_prefers_plain_message_text():
    result = {
        "outputs": [
            {
                "outputs": [
                    {
                        "component_id": "viz",
                        "component_display_name": "材料科学·应力—应变图",
                        "outputs": {
                            "report": {"type": "object", "message": "应力—应变图已完成。生成文件 4 个。"}
                        },
                    }
                ]
            }
        ]
    }
    compact = _compact_run_result(result)
    report = compact["outputs"][0]["outputs"]["report"]
    assert "应力—应变图已完成" in report["text"]
