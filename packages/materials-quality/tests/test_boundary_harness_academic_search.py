"""Boundary tests: malformed provider payloads must surface as warnings."""

import pytest

from materials_quality.agent import academic_search


@pytest.mark.parametrize(
    ("provider", "body"),
    [
        ("crossref", b"[]"),
        ("crossref", b"{}"),
        ("crossref", b'{"message": []}'),
        ("crossref", b'{"message": {"items": "not-a-list"}}'),
        ("openalex", b'{"results": "not-a-list"}'),
        ("openalex", b"null"),
        ("europe_pmc", b'{"resultList": []}'),
        ("semantic_scholar", b'{"data": 5}'),
        ("datacite", b'{"data": 5}'),
    ],
)
def test_wrong_shaped_provider_payload_surfaces_a_warning(monkeypatch, provider, body):
    monkeypatch.setattr(academic_search, "_get", lambda url, params: body)

    result = academic_search.search("titanium alloy tensile strength", providers=[provider])

    assert result["records"] == []
    assert result["warnings"] == [{"provider": provider, "error": "ValueError"}]
