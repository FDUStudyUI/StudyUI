import json
import os
import subprocess
import sys

import pandas as pd
import pytest

from materials_quality.science.checkpoints import checkpoint_scope, invoke
from materials_quality.science.contracts import NodeResult


def test_cross_process_checkpoint_preserves_features_and_metadata(tmp_path):
    program = """
import json,sys,numpy as np,pandas as pd
from materials_quality.science.checkpoints import checkpoint_scope,invoke
from materials_quality.science.contracts import NodeResult
table=pd.DataFrame({'x':[1.,2.,3.]}); table.attrs={'units':{'x':'nm'}}
def compute():
    if sys.argv[2]=='second': raise AssertionError('Recomputed completed scientific step')
    return NodeResult(table=table, features=pd.DataFrame({'peak':[2.]}),
                      data={'array':np.array([1.,np.nan]),'n':np.int64(3)})
with checkpoint_scope(sys.argv[1]) as records:
    result,_=invoke('materials.spectra',table,{}, {},[],compute)
assert result.table.attrs==table.attrs
assert result.features.iloc[0,0]==2.
assert isinstance(result.data['n'],np.int64)
assert np.isnan(result.data['array'][1])
print(json.dumps(records))
"""
    for phase, expected in [("first", "computed"), ("second", "reused")]:
        output = subprocess.check_output(
            [sys.executable, "-c", program, str(tmp_path), phase], env=os.environ
        )
        assert json.loads(output)[0]["status"] == expected


def test_parameter_change_recomputes_only_affected_branch_and_corruption_recovers(tmp_path):
    calls = []
    source = pd.DataFrame({"x": [1.0, 2.0, 3.0]})

    def run(factor):
        with checkpoint_scope(tmp_path) as records:
            for name, multiplier in [("unchanged", 1), ("changed", factor)]:

                def compute(m=multiplier, n=name):
                    calls.append(n)
                    return NodeResult(table=source * m)

                invoke(
                    "preprocess.normalize", source, {"factor": multiplier, "branch": name}, {}, [], compute
                )
        return records

    assert [r["status"] for r in run(2)] == ["computed", "computed"]
    assert [r["status"] for r in run(3)] == ["reused", "computed"]
    assert calls == ["unchanged", "changed", "changed"]
    for path in tmp_path.rglob("*.parquet"):
        path.write_bytes(b"damaged")
    assert [r["status"] for r in run(3)] == ["computed", "computed"]


def test_failed_and_effectful_operations_are_not_reused(tmp_path):
    with checkpoint_scope(tmp_path) as records:
        for _ in range(2):
            result, _ = invoke(
                "materials.spectra",
                None,
                {},
                {},
                [],
                lambda: NodeResult(data={"execution_status": "partial_failed"}),
            )
            assert result.data["execution_status"] == "partial_failed"
        invoke("export.report", None, {}, {}, [], lambda: NodeResult(artifacts=["report.html"]))
    assert [r["status"] for r in records] == ["incomplete_not_saved", "incomplete_not_saved"]
    assert not list(tmp_path.rglob("result.json"))


def test_computation_failure_propagates_without_a_cached_success(tmp_path):
    with checkpoint_scope(tmp_path), pytest.raises(ValueError, match="bad method"):
        invoke("materials.spectra", None, {}, {}, [], lambda: (_ for _ in ()).throw(ValueError("bad method")))
    assert not list(tmp_path.rglob("result.json"))


def test_project_checkpoints_support_long_windows_paths(tmp_path):
    root = tmp_path / ("a" * 90) / ("b" * 90)
    frame = pd.DataFrame({"x": [1.0, 2.0]})
    for expected in ("computed", "reused"):
        with checkpoint_scope(root) as records:
            invoke("materials.spectra", frame, {}, {}, [], lambda: NodeResult(table=frame))
        assert records[0]["status"] == expected, records
