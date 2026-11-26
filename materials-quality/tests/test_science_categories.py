from materials_quality.science import catalog
from materials_quality.science.categories import CATEGORY_LABELS, category_label


def test_catalog_categories_are_stable_ids_with_labels():
    entries = catalog.entries()
    assert len(entries) >= 40
    for entry in entries:
        assert entry["category"] in CATEGORY_LABELS, entry["key"]
        assert entry["category_label"] == CATEGORY_LABELS[entry["category"]], entry["key"]


def test_every_declared_category_is_used():
    used = {entry["category"] for entry in catalog.entries()}
    assert used == set(CATEGORY_LABELS)


def test_category_label_falls_back_to_value():
    assert category_label("unknown_group") == "unknown_group"
    assert category_label("preprocessing") == "预处理"
