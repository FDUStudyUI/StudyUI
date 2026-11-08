"""Boundary regressions: model profile validation and re-save preservation.

Round-2 boundary campaign on ModelProfiles. These cases lost user configuration
or raised non-ValueError exceptions on the pre-fix tree; the credential store is
faked, no real keyring or network is touched.
"""

import pytest

from materials_quality.agent.model_profiles import ModelProfiles

BASE = {"name": "M", "base_url": "https://example.com/v1", "model": "m"}


class FakeKeyring:
    values = {}

    @classmethod
    def set_password(cls, service, ref, value):
        cls.values[(service, ref)] = value

    @classmethod
    def get_password(cls, service, ref):
        return cls.values.get((service, ref))

    @classmethod
    def delete_password(cls, service, ref):
        cls.values.pop((service, ref), None)


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(ModelProfiles, "_keyring", staticmethod(lambda: FakeKeyring))
    return ModelProfiles(tmp_path / "settings.json")


def test_resave_without_context_window_preserves_explicit_value(profiles):
    profiles.save(**BASE, context_window=8192, max_output_tokens=4096)

    profiles.save(**BASE)

    public = profiles.public()
    assert public["context_window"] == 8192
    assert public["max_output_tokens"] == 4096


@pytest.mark.parametrize("field", ["context_window", "max_output_tokens"])
@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"), 2048.5])
def test_non_integral_or_non_finite_token_limits_raise_valueerror(profiles, field, value):
    with pytest.raises(ValueError):
        profiles.save(**BASE, **{field: value})


@pytest.mark.parametrize("value", [[], {}, []])
def test_wrong_typed_reasoning_effort_raises_valueerror(profiles, value):
    with pytest.raises(ValueError, match="思考等级"):
        profiles.save(**BASE, reasoning_effort=value)


@pytest.mark.parametrize("field", ["name", "model"])
def test_null_text_fields_are_rejected_instead_of_written_as_none(profiles, field):
    kwargs = dict(BASE)
    kwargs[field] = None
    with pytest.raises(ValueError, match="请填写"):
        profiles.save(**kwargs)
