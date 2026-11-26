import requests

from materials_quality.agent import academic_search


class _Response:
    def __init__(self, status_code, body=b"{}", headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}

    def iter_content(self, _size):
        yield self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def close(self):
        pass


def test_get_retries_transient_status(monkeypatch):
    calls = []
    responses = [_Response(503, headers={"Retry-After": "0"}), _Response(200, body=b'{"ok": 1}')]

    def fake_get(*_args, **_kwargs):
        calls.append(1)
        return responses.pop(0)

    monkeypatch.setattr(academic_search.requests, "get", fake_get)
    monkeypatch.setattr(academic_search.time, "sleep", lambda _s: None)
    assert academic_search._get("https://example.test", {}) == b'{"ok": 1}'
    assert len(calls) == 2


def test_search_warning_records_http_status(monkeypatch):
    def failing(_query, _limit):
        raise requests.HTTPError(response=_Response(429))

    monkeypatch.setitem(academic_search._SEARCH, "crossref", failing)
    result = academic_search.search("materials", providers=("crossref",), limit=1)
    assert result["warnings"] == [{"provider": "crossref", "error": "HTTPError", "status": 429}]
