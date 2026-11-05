import json

from materials_quality.agent import academic_search


def test_zenodo_identifier_uses_fixed_datacite_doi_endpoint(monkeypatch):
    calls = []

    def get(url, params):
        calls.append((url, params))
        return json.dumps({"data": {"attributes": {
            "doi": "10.5281/zenodo.12345",
            "titles": [{"title": "Open research data"}],
            "descriptions": [{"description": "<p>Measurement metadata</p>"}],
            "relatedIdentifiers": [{"relatedIdentifier": "10.1/example", "relatedIdentifierType": "DOI", "relationType": "IsSupplementTo"}],
        }}}).encode()

    monkeypatch.setattr(academic_search, "_get", get)
    result = academic_search.search("Zenodo record 12345 battery experiment", providers=["datacite"])
    assert calls == [("https://api.datacite.org/dois/10.5281%2Fzenodo.12345", {})]
    assert result["records"][0]["title"] == "Open research data"
    assert "<p>" not in result["records"][0]["description"]
    assert result["records"][0]["related_identifiers"][0]["relation"] == "IsSupplementTo"
    assert result["full_text_fetched"] is False
