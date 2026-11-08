"""Regression tests: one malformed provider record must not discard an entire search."""

import json

import pytest

from materials_quality.agent import academic_search


def _install(monkeypatch, payload):
    monkeypatch.setattr(
        academic_search,
        "_get",
        lambda url, params: json.dumps(payload).encode(),
    )


def _good_crossref():
    return {
        "title": ["Good record"],
        "DOI": "10.1000/good",
        "published": {"date-parts": [[2024]]},
        "author": [{"given": "A", "family": "Li"}],
        "container-title": ["Journal"],
        "URL": "https://example.org/good",
    }


def _good_openalex():
    return {
        "title": "Good record",
        "doi": "https://doi.org/10.1000/good",
        "publication_year": 2024,
        "authorships": [{"author": {"display_name": "Alice"}}],
        "primary_location": {"source": {"display_name": "Journal"}},
        "abstract_inverted_index": {"hello": [0]},
    }


def _good_europe_pmc():
    return {
        "title": "Good record",
        "doi": "10.1000/good",
        "firstPublicationDate": "2024-01-01",
        "authorList": {"author": [{"fullName": "A Li"}]},
        "journalTitle": "Journal",
        "pmid": "123",
        "abstractText": "hello",
    }


def _good_semantic_scholar():
    return {
        "title": "Good record",
        "externalIds": {"DOI": "10.1000/good"},
        "year": 2024,
        "authors": [{"name": "Alice"}],
        "venue": "Journal",
        "url": "https://example.org/good",
        "abstract": "hello",
    }


def _good_datacite():
    return {
        "attributes": {
            "doi": "10.1000/good",
            "publicationYear": 2024,
            "titles": [{"title": "Good record"}],
            "descriptions": [{"description": "<p>hello</p>"}],
            "creators": [{"name": "Alice"}],
            "relatedIdentifiers": [],
            "publisher": "Zenodo",
            "url": "https://example.org/good",
        }
    }


@pytest.mark.parametrize(
    ("provider", "payload", "expected_title"),
    [
        (
            "crossref",
            {
                "message": {
                    "items": [
                        {
                            "title": ["Incomplete record"],
                            "DOI": "10.1000/bad",
                            "published": None,
                            "author": None,
                            "container-title": ["Journal"],
                            "URL": "https://example.org/bad",
                        },
                        _good_crossref(),
                    ]
                }
            },
            "Good record",
        ),
        (
            "openalex",
            {
                "results": [
                    {
                        "title": "Incomplete record",
                        "authorships": [{"author": None}],
                        "primary_location": {"source": None},
                    },
                    _good_openalex(),
                ]
            },
            "Good record",
        ),
        (
            "europe_pmc",
            {
                "resultList": {
                    "result": [
                        {
                            "title": "Incomplete record",
                            "firstPublicationDate": None,
                            "authorList": None,
                        },
                        _good_europe_pmc(),
                    ]
                }
            },
            "Good record",
        ),
        (
            "semantic_scholar",
            {
                "data": [
                    {"title": "Incomplete record", "authors": None, "externalIds": None},
                    _good_semantic_scholar(),
                ]
            },
            "Good record",
        ),
        (
            "datacite",
            {
                "data": [
                    {
                        "attributes": {
                            "doi": "10.1000/bad",
                            "titles": None,
                            "descriptions": None,
                            "creators": None,
                            "relatedIdentifiers": None,
                        }
                    },
                    _good_datacite(),
                ]
            },
            "Good record",
        ),
    ],
)
def test_single_incomplete_record_does_not_discard_provider_results(
    monkeypatch, provider, payload, expected_title
):
    _install(monkeypatch, payload)

    result = academic_search.search("titanium alloy tensile strength", providers=[provider])

    assert result["warnings"] == []
    assert [record["title"] for record in result["records"]][-1] == expected_title
    assert len(result["records"]) == 2


def test_provider_wide_failure_still_returns_a_warning(monkeypatch):
    def broken(url, params):
        raise TimeoutError("provider timed out")

    monkeypatch.setattr(academic_search, "_get", broken)

    result = academic_search.search("titanium alloy tensile strength", providers=["crossref"])

    assert result["records"] == []
    assert result["warnings"] == [{"provider": "crossref", "error": "TimeoutError"}]
