import pandas as pd
import pytest
from scipy.stats import ttest_ind

from materials_quality.science.contrast_study import contrast_study


def fixture():
    return pd.DataFrame(
        [
            {
                "group": g,
                "variable": "v",
                "experimental_unit": f"{g}{i}",
                "sample_id": f"{g}{i}-{r}",
                "value": v,
            }
            for g, values in [("A", [1.0, 2, 3]), ("B", [4.0, 6, 8])]
            for i, v in enumerate(values)
            for r in range(4)
        ]
    )


def test_replicates_aggregate_before_welch_and_effect():
    result = contrast_study(fixture())
    assert len(result.table) == 6
    assert result.data["descriptives"][0]["count"] == 3
    pair = result.features.iloc[0]
    assert pair.p_raw == pytest.approx(ttest_ind([1, 2, 3], [4, 6, 8], equal_var=False).pvalue)
    assert pair.effect_size < 0
    assert pair.p_adjusted == pair.p_raw


def test_paired_units_alignment_and_design_guard():
    frame = fixture()
    frame["experimental_unit"] = frame.experimental_unit.str[1:]
    with pytest.raises(ValueError, match="independent"):
        contrast_study(frame)
    result = contrast_study(frame, config={"design": "paired"})
    assert result.features.iloc[0].n_pairs == 3
    frame = frame.loc[~((frame.group == "B") & (frame.experimental_unit == "2"))]
    with pytest.raises(ValueError, match="matching"):
        contrast_study(frame, config={"design": "paired"})


def test_three_group_welch_and_holm():
    f = fixture()
    c = f.loc[f.group == "A"].copy()
    c.group = "C"
    c.experimental_unit = "C" + c.experimental_unit
    c.value += 10
    r = contrast_study(pd.concat([f, c]), config={"correction": "holm"})
    assert r.data["omnibus"][0]["method"] == "welch_anova"
    assert len(r.features) == 3
    assert (r.features.p_adjusted >= r.features.p_raw).all()


def test_rank_strategy_oracle_and_degenerate_variance():
    from scipy.stats import mannwhitneyu

    r = contrast_study(fixture(), config={"strategy": "nonparametric", "correction": "fdr_bh"})
    expected = mannwhitneyu([1, 2, 3], [4, 6, 8], alternative="two-sided")
    assert r.features.iloc[0].p_raw == pytest.approx(expected.pvalue)
    assert r.features.iloc[0].effect_size == -1
    f = fixture()
    f["value"] = 2.0
    r = contrast_study(f)
    assert r.data["pairwise"][0]["p_raw"] is None
    assert r.data["pairwise"][0]["effect_size"] is None


def test_native_contrast_component():
    import asyncio

    from lfx.custom import Component
    from lfx.custom.eval import eval_custom_component_code
    from lfx.graph import Graph
    from lfx.schema import DataFrame

    from components.materials_batch.contrast_study import ContrastStudy

    assert ContrastStudy.__bases__ == (Component,)
    node = ContrastStudy().set(input_table=DataFrame(fixture()))
    results, _ = asyncio.run(node.build_results())
    assert len(results["features"]) == 1
    assert len(results["units"]) == 6
    payload = Graph(start=node, end=node).dump()
    source = payload["data"]["nodes"][0]["data"]["node"]["template"]["code"]["value"]
    assert eval_custom_component_code(source).__name__ == "ContrastStudy"
