from pathlib import Path

import pytest

from materials_quality.component_manifest import component_manifest, verify_discovery


def test_manifest_includes_extra_native_nodes_and_rejects_incomplete_discovery():
    root = Path(__file__).resolve().parents[1] / "components"
    expected = component_manifest(root)
    assert "StudyUIAIAnalysis" in expected["materials_skills"]
    assert "ScienceFixtureBundle" in expected["materials_sources"]
    discovered = {category: {name: {} for name in names} for category, names in expected.items()}
    assert verify_discovery(discovered, root) == sum(map(len, expected.values()))
    del discovered["materials_skills"]["StudyUIAIAnalysis"]
    with pytest.raises(ValueError, match="StudyUIAIAnalysis"):
        verify_discovery(discovered, root)


def test_server_extension_names_preserve_exact_category_and_identity():
    root = Path(__file__).resolve().parents[1] / "components"
    expected = component_manifest(root)
    discovered = {
        category: {f"ext:{category}:{name}@extra": {} for name in names}
        for category, names in expected.items()
    }
    assert verify_discovery(discovered, root) == sum(map(len, expected.values()))
    discovered["materials_skills"]["ext:wrong_category:StudyUIAIAnalysis@extra"] = discovered[
        "materials_skills"
    ].pop("ext:materials_skills:StudyUIAIAnalysis@extra")
    with pytest.raises(ValueError, match="StudyUIAIAnalysis"):
        verify_discovery(discovered, root)


def test_duplicate_canonical_and_extension_entries_are_not_silently_collapsed():
    root = Path(__file__).resolve().parents[1] / "components"
    expected = component_manifest(root)
    discovered = {category: {name: {} for name in names} for category, names in expected.items()}
    discovered["materials_skills"]["ext:materials_skills:StudyUIAIAnalysis@extra"] = {}
    with pytest.raises(ValueError, match="duplicate|Duplicate"):
        verify_discovery(discovered, root)
