"""Stable category identifiers for the science operation catalog.

Categories are stored as stable, locale-independent ids. The Chinese display
label lives in ``category_label`` so grouping stays consistent for humans and
for agents that filter by category.
"""

from __future__ import annotations

CATEGORY_LABELS: dict[str, str] = {
    "data_ingestion": "数据接入",
    "content_extraction": "内容提取",
    "preprocessing": "预处理",
    "materials_analysis": "材料专业分析",
    "statistics": "统计与建模",
    "visualization": "可视化与报告",
    "literature": "文献与证据",
}


def category_label(value: str) -> str:
    """Return the display label for a stable category id (fallback: the value)."""
    return CATEGORY_LABELS.get(str(value), str(value))
