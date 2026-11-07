import json

from materials_quality.agent import academic_search


def test_zenodo_identifier_uses_fixed_datacite_doi_endpoint(monkeypatch):
    calls = []

    def get(url, params):
        calls.append((url, params))
        return json.dumps(
            {
                "data": {
                    "attributes": {
                        "doi": "10.5281/zenodo.12345",
                        "titles": [{"title": "Open research data"}],
                        "descriptions": [{"description": "<p>Measurement metadata</p>"}],
                        "relatedIdentifiers": [
                            {
                                "relatedIdentifier": "10.1/example",
                                "relatedIdentifierType": "DOI",
                                "relationType": "IsSupplementTo",
                            }
                        ],
                    }
                }
            }
        ).encode()

    monkeypatch.setattr(academic_search, "_get", get)
    result = academic_search.search("Zenodo record 12345 battery experiment", providers=["datacite"])
    assert calls == [("https://api.datacite.org/dois/10.5281%2Fzenodo.12345", {})]
    assert result["records"][0]["title"] == "Open research data"
    assert "<p>" not in result["records"][0]["description"]
    assert result["records"][0]["related_identifiers"][0]["relation"] == "IsSupplementTo"
    assert result["records"][0]["abstract"] == "Measurement metadata"
    assert result["full_text_fetched"] is False


def test_openalex_abstract_inversion(monkeypatch):
    def get(url, params):
        return json.dumps(
            {
                "results": [
                    {
                        "title": "Study of Ti Alloys",
                        "doi": "https://doi.org/10.1000/182",
                        "publication_year": 2024,
                        "authorships": [{"author": {"display_name": "Alice"}}],
                        "abstract_inverted_index": {
                            "Titanium": [0],
                            "alloys": [1],
                            "exhibit": [2],
                            "high": [3],
                            "strength.": [4],
                        },
                    }
                ]
            }
        ).encode()

    monkeypatch.setattr(academic_search, "_get", get)
    result = academic_search.search("Ti alloy tensile strength", providers=["openalex"])
    assert len(result["records"]) == 1
    assert result["records"][0]["abstract"] == "Titanium alloys exhibit high strength."


def test_arxiv_abstract_extraction(monkeypatch):
    xml_data = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Machine Learning for Materials</title>
        <id>http://arxiv.org/abs/2401.00001v1</id>
        <published>2024-01-01T00:00:00Z</published>
        <author><name>Bob</name></author>
        <summary>This work demonstrates automated workflow construction.</summary>
      </entry>
    </feed>
    """
    monkeypatch.setattr(academic_search, "_get", lambda url, params: xml_data.encode())
    result = academic_search.search("Machine Learning for Materials", providers=["arxiv"])
    assert len(result["records"]) == 1
    assert result["records"][0]["abstract"] == "This work demonstrates automated workflow construction."
