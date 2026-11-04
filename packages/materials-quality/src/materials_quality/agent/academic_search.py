"""Bounded scholarly search against a fixed list of research metadata services."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

PROVIDERS = ("crossref", "openalex", "semantic_scholar", "europe_pmc", "datacite", "arxiv")
TIMEOUT = (5, 18)
MAX_RESPONSE_BYTES = 3_000_000
HEADERS = {"User-Agent": "StudyUI/0.8 (research metadata discovery)"}


def _get(url, params):
    response = requests.get(
        url, params=params, headers=HEADERS, timeout=TIMEOUT, allow_redirects=False, stream=True
    )
    response.raise_for_status()
    chunks, total = [], 0
    for chunk in response.iter_content(64_000):
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise ValueError("Research metadata response exceeded the size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _crossref(query, limit):
    import json

    body = json.loads(_get("https://api.crossref.org/works", {"query.bibliographic": query, "rows": limit}))
    records = body.get("message", {}).get("items", [])
    out = []
    for row in records:
        date = row.get("published", {}).get("date-parts", [[None]])
        out.append(
            {
                "title": (row.get("title") or [None])[0],
                "doi": row.get("DOI"),
                "year": (date[0] or [None])[0],
                "authors": [
                    " ".join(filter(None, [a.get("given"), a.get("family")])) for a in row.get("author", [])
                ],
                "venue": (row.get("container-title") or [None])[0],
                "url": row.get("URL"),
                "provider": "Crossref",
            }
        )
    return out


def _openalex(query, limit):
    import json

    body = json.loads(_get("https://api.openalex.org/works", {"search": query, "per-page": limit}))
    return [
        {
            "title": row.get("title"),
            "doi": row.get("doi"),
            "year": row.get("publication_year"),
            "authors": [a.get("author", {}).get("display_name") for a in row.get("authorships", [])],
            "venue": (row.get("primary_location") or {}).get("source", {}).get("display_name"),
            "url": row.get("doi") or row.get("id"),
            "provider": "OpenAlex",
        }
        for row in body.get("results", [])
    ]


def _semantic_scholar(query, limit):
    import json

    params = {
        "query": query,
        "limit": limit,
        "fields": "title,authors,year,venue,externalIds,url,openAccessPdf",
    }
    body = json.loads(_get("https://api.semanticscholar.org/graph/v1/paper/search", params))
    return [
        {
            "title": row.get("title"),
            "doi": (row.get("externalIds") or {}).get("DOI"),
            "year": row.get("year"),
            "authors": [a.get("name") for a in row.get("authors", [])],
            "venue": row.get("venue"),
            "url": row.get("url"),
            "provider": "Semantic Scholar",
        }
        for row in body.get("data", [])
    ]


def _europe_pmc(query, limit):
    import json

    params = {"query": query, "format": "json", "pageSize": limit, "resultType": "core"}
    body = json.loads(_get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params))
    return [
        {
            "title": row.get("title"),
            "doi": row.get("doi"),
            "year": row.get("firstPublicationDate", "")[:4],
            "authors": [a.get("fullName") for a in (row.get("authorList") or {}).get("author", [])],
            "venue": row.get("journalTitle"),
            "url": (
                "https://europepmc.org/article/MED/" + str(row["pmid"])
                if row.get("pmid")
                else row.get("pmcid")
            ),
            "provider": "Europe PMC",
        }
        for row in body.get("resultList", {}).get("result", [])
    ]


def _datacite(query, limit):
    import json

    body = json.loads(_get("https://api.datacite.org/dois", {"query": query, "page[size]": limit}))
    out = []
    for item in body.get("data", []):
        attrs = item.get("attributes", {})
        title = next((x.get("title") for x in attrs.get("titles", []) if x.get("title")), None)
        out.append(
            {
                "title": title,
                "doi": attrs.get("doi"),
                "year": attrs.get("publicationYear"),
                "authors": [x.get("name") or x.get("givenName") for x in attrs.get("creators", [])],
                "venue": attrs.get("publisher"),
                "url": attrs.get("url"),
                "provider": "DataCite",
            }
        )
    return out


def _arxiv(query, limit):
    raw = _get(
        "https://export.arxiv.org/api/query",
        {"search_query": "all:" + query, "start": 0, "max_results": limit},
    )
    root = ET.fromstring(raw)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    return [
        {
            "title": " ".join((row.findtext("a:title", default="", namespaces=ns)).split()),
            "doi": row.findtext("a:doi", namespaces=ns),
            "year": (row.findtext("a:published", default="", namespaces=ns) or "")[:4],
            "authors": [a.findtext("a:name", default="", namespaces=ns) for a in row.findall("a:author", ns)],
            "venue": "arXiv",
            "url": row.findtext("a:id", namespaces=ns),
            "provider": "arXiv",
        }
        for row in root.findall("a:entry", ns)
    ]


_SEARCH = {
    "crossref": _crossref,
    "openalex": _openalex,
    "semantic_scholar": _semantic_scholar,
    "europe_pmc": _europe_pmc,
    "datacite": _datacite,
    "arxiv": _arxiv,
}


def search(query: str, *, providers=None, limit=5):
    query = str(query).strip()
    if not 2 <= len(query) <= 500:
        raise ValueError("Search query must be between 2 and 500 characters")
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("Search result limit must be between 1 and 10 per provider")
    selected = tuple(providers or ("crossref", "openalex", "semantic_scholar", "europe_pmc"))
    if not selected or len(selected) > len(PROVIDERS) or any(name not in _SEARCH for name in selected):
        raise ValueError("Only registered scholarly databases are allowed")
    records, warnings = [], []
    for provider in selected:
        try:
            records.extend(_SEARCH[provider](query, limit))
        except Exception as exc:
            warnings.append({"provider": provider, "error": type(exc).__name__})
    seen, unique = set(), []
    for record in records:
        key = (str(record.get("doi") or "").casefold(), str(record.get("title") or "").casefold())
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return {
        "providers": list(selected),
        "full_text_fetched": False,
        "records": unique[:50],
        "warnings": warnings,
    }
