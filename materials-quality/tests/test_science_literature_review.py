"""Regression checks for grounded measurements and authoritative source records."""

import json
import threading
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from materials_quality.science import literature as lit


@pytest.fixture
def claim_endpoint(monkeypatch):
    state = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"choices": [{"message": {"content": json.dumps({"claims": [state["claim"]]})}}]}
                ).encode()
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("LIT_REVIEW_TEST_KEY", "synthetic-local-only")
    config = {
        "method": "llm",
        "llm": {
            "url": f"http://127.0.0.1:{server.server_port}/",
            "model": "local-test",
            "api_key_env": "LIT_REVIEW_TEST_KEY",
        },
    }
    yield state, config
    server.shutdown()
    server.server_close()
    thread.join()


def _extract_claim(endpoint, text, value, unit):
    state, config = endpoint
    state["claim"] = {
        "source_id": "a",
        "property": "strength",
        "value": value,
        "unit": unit,
        "quote": text,
        "span_start": 0,
        "span_end": len(text),
        "material": None,
        "preparation": None,
        "test_condition": None,
    }
    return lit.extract(data={"documents": [{"source_id": "a", "text": text}]}, config=config)


@pytest.mark.parametrize(
    "text,value",
    [
        ("strength was -100 MPa.", "100"),
        ("strength was 100 MPa.", "10"),
        ("strength was 1e3 MPa.", "3"),
    ],
)
def test_numeric_strings_cannot_match_part_of_signed_measurements(claim_endpoint, text, value):
    with pytest.raises(ValueError, match="numeric"):
        _extract_claim(claim_endpoint, text, value, "MPa")


@pytest.mark.parametrize(
    "text,value",
    [
        ("strength was -100 MPa.", "-100"),
        ("strength was 1e3 MPa.", "1000"),
        ("strength was .5 MPa.", "0.5"),
    ],
)
def test_complete_numeric_strings_preserve_valid_measurements(claim_endpoint, text, value):
    result = _extract_claim(claim_endpoint, text, value, "MPa")
    assert result.table.iloc[0]["value"] == value


@pytest.mark.parametrize(
    "text,unit",
    [
        ("strength was 100 MPa.", "Pa"),
        ("strength was 100 kPa.", "Pa"),
        ("strength was 100 Pa/s.", "Pa"),
    ],
)
def test_unit_must_match_a_complete_prefixed_or_compound_token(claim_endpoint, text, unit):
    with pytest.raises(ValueError, match="unit"):
        _extract_claim(claim_endpoint, text, 100, unit)


@pytest.mark.parametrize("text", ["strength was 100 MPa.", "strength was 100MPa."])
def test_exact_unit_with_sentence_punctuation_is_accepted(claim_endpoint, text):
    result = _extract_claim(claim_endpoint, text, 100, "MPa")
    assert result.table.iloc[0]["unit"] == "MPa"


@pytest.mark.parametrize(
    "override",
    [
        {"doi": "10.1234/fabricated"},
        {"page": 999},
        {"text": "fabricated 999 MPa", "quote": "999 MPa"},
    ],
)
def test_source_records_cannot_replace_authoritative_text_or_provenance(override):
    data = {
        "documents": [{"source_id": "a", "text": "strength was 100 MPa.", "doi": "10.1234/real", "page": 2}],
        "records": [{"source_id": "a", "quote": "100 MPa", **override}],
    }
    original = deepcopy(data)
    with pytest.raises(ValueError, match="source|provenance"):
        lit.sources(data=data)
    assert data == original


def test_source_registry_keeps_original_locations_and_validates_original_spans():
    data = {
        "documents": [{"source_id": "a", "text": "strength was 100 MPa.", "doi": "10.1234/real", "page": 2}],
        "records": [{"source_id": "a", "quote": "100 MPa", "span_start": 13, "span_end": 20}],
    }
    original = deepcopy(data)
    result = lit.sources(data=data)
    assert result.data["sources"] == [
        {
            "doi": "10.1234/real",
            "page": 2,
            "source_id": "a",
            "quote": "100 MPa",
            "span_start": 13,
            "span_end": 20,
            "citation": "https://doi.org/10.1234/real; page 2",
        }
    ]
    assert data == original
    data["records"][0]["span_start"] = 0
    with pytest.raises(ValueError, match="span"):
        lit.sources(data=data)


def test_source_span_cannot_extend_beyond_the_original_text():
    text = "strength was 100 MPa."
    with pytest.raises(ValueError, match="span"):
        lit.sources(
            data={
                "documents": [{"source_id": "a", "text": text}],
                "records": [{"source_id": "a", "quote": text, "span_start": 0, "span_end": 999}],
            }
        )


@pytest.mark.parametrize("start,end", [("0", 20), (0, "20"), (False, 20)])
def test_source_spans_require_integer_indices(start, end):
    text = "strength was 100 MPa."
    with pytest.raises(ValueError, match="span"):
        lit.sources(
            data={
                "documents": [{"source_id": "a", "text": text}],
                "records": [{"source_id": "a", "quote": text, "span_start": start, "span_end": end}],
            }
        )
