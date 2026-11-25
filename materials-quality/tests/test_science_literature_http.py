"""Real local HTTP protocol tests: no paid services or mock network success."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from test_science_literature import DOCS, lit


@pytest.fixture
def endpoint():
    state = {"requests": [], "claims": None, "redirect": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            state["requests"].append(("GET", self.path, dict(self.headers)))
            record = {
                "DOI": "10.1234/a",
                "title": ["ZnO sensor"],
                "author": [{"given": "A", "family": "Li"}],
                "container-title": ["Test Journal"],
                "published": {"date-parts": [[2024]]},
            }
            self.send_response(200)
            self.end_headers()
            result = record if "/works/" in self.path else {"items": [record], "total-results": 1}
            self.wfile.write(json.dumps({"message": result}).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append(("POST", self.path, dict(self.headers), body))
            if state["redirect"]:
                self.send_response(302)
                self.send_header("Location", "http://localhost:1/stolen")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"choices": [{"message": {"content": json.dumps({"claims": state["claims"]})}}]}
                ).encode()
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", state
    server.shutdown()
    server.server_close()
    thread.join()


def test_crossref_search_and_metadata_real_http(endpoint):
    url, state = endpoint
    result = lit().search(
        config={
            "provider": "crossref",
            "base_url": url,
            "query": "ZnO AND NOT GaN",
            "method": "boolean",
            "rows": 2,
        }
    )
    assert result.table.iloc[0]["authors"] == ["A Li"]
    assert result.data["candidate_filtering"] is True
    query = parse_qs(urlparse(state["requests"][0][1]).query)
    assert query["rows"] == ["2"] and "query.bibliographic" in query
    meta = lit().metadata(config={"provider": "crossref", "base_url": url, "doi": "10.1234/a"})
    assert meta.table.iloc[0]["year"] == 2024
    assert state["requests"][1][1].endswith("/works/10.1234%2Fa")


def good_claim():
    return {
        "source_id": "a",
        "property": "strength",
        "value": 100,
        "unit": "MPa",
        "quote": "100 MPa",
        "span_start": 49,
        "span_end": 56,
        "material": "ZnO",
        "preparation": "sputtering",
        "test_condition": "300 K",
    }


def test_llm_actual_json_schema_adapter_and_grounding(endpoint, monkeypatch):
    url, state = endpoint
    monkeypatch.setenv("LIT_TEST_KEY", "test-secret-local-only")
    claim = good_claim()
    claim["span_start"] = DOCS["documents"][0]["text"].index(claim["quote"])
    claim["span_end"] = claim["span_start"] + len(claim["quote"])
    state["claims"] = [claim]
    config = {
        "method": "llm",
        "llm": {"url": url + "/v1/chat/completions", "model": "test-local", "api_key_env": "LIT_TEST_KEY"},
    }
    result = lit().extract(data=DOCS, config=config)
    assert result.table.iloc[0]["value"] == 100
    request = state["requests"][-1]
    assert request[2]["Authorization"] == "Bearer test-secret-local-only"
    assert request[3]["response_format"]["type"] == "json_schema"
    assert "test-secret" not in repr(result)
    for change, error in [
        ({"source_id": "invented"}, "source"),
        ({"value": 999}, "numeric"),
        ({"quote": "99 MPa"}, "quote"),
        ({"span_start": 0}, "span"),
        ({"material": "GaN"}, "material"),
    ]:
        state["claims"] = [{**claim, **change}]
        with pytest.raises(ValueError, match=error):
            lit().extract(data=DOCS, config=config)
    state["claims"] = [{"source_id": "a"}]
    with pytest.raises(ValueError, match="schema"):
        lit().extract(data=DOCS, config=config)
    state["claims"] = [claim]
    state["redirect"] = True
    with pytest.raises(ValueError, match="redirect"):
        lit().extract(data=DOCS, config=config)


def test_llm_requires_explicit_environment_credential(endpoint):
    url, state = endpoint
    with pytest.raises(ValueError, match="credential|environment"):
        lit().extract(
            data=DOCS,
            config={"method": "llm", "llm": {"url": url, "model": "test", "api_key_env": "LIT_NO_SUCH_KEY"}},
        )
    assert state["requests"] == []


def test_llm_summary_uses_only_validated_source_citations(endpoint, monkeypatch):
    url, state = endpoint
    monkeypatch.setenv("LIT_TEST_KEY", "test-secret-local-only")
    claim = good_claim()
    claim["span_start"] = DOCS["documents"][0]["text"].index(claim["quote"])
    claim["span_end"] = claim["span_start"] + len(claim["quote"])
    state["claims"] = [claim]
    result = lit().summary(
        data=DOCS,
        config={
            "question": "strength",
            "method": "llm",
            "llm": {
                "url": url + "/v1/chat/completions",
                "model": "local-test",
                "api_key_env": "LIT_TEST_KEY",
            },
        },
    )
    assert "https://doi.org/10.1234/a" in result.data["summary"]
    assert result.data["points"][0]["field_evidence"]["material"]["quote"] == "ZnO"
    state["claims"] = [{**claim, "source_id": "hallucinated"}]
    with pytest.raises(ValueError, match="source"):
        lit().summary(
            data=DOCS,
            config={
                "question": "strength",
                "method": "llm",
                "llm": {"url": url, "model": "local-test", "api_key_env": "LIT_TEST_KEY"},
            },
        )
