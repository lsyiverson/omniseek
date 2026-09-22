#!/usr/bin/env python3
"""Semantic Scholar: 225M+ papers, citation graphs, TLDR summaries.

Free public API. Without an API key the shared pool allows ~5000 requests /
5 minutes; with a key (``S2_API_KEY`` env var) you get a guaranteed 1 RPS.

Docs: https://api.semanticscholar.org/api-docs/
Key endpoints:
  GET /graph/v1/paper/search?query=<q>&limit=<n>&fields=...   — paper search
  GET /graph/v1/paper/{id}?fields=...                          — paper lookup

Allowlisted inline qualifiers in the query string:
  year:2020   year:2020-2023   year:2020-   year:-2023
  venue:NeurIPS
  min_citations:50
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search"
PAPER_ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper"

_YEAR_RE = re.compile(r"(?:^|\s)year:(\d{4}(?:-\d{0,4})?|-\d{4})", re.IGNORECASE)
_VENUE_RE = re.compile(r"(?:^|\s)venue:([^\s,]+)", re.IGNORECASE)
_MINCITE_RE = re.compile(r"(?:^|\s)min_citations?:(\d+)", re.IGNORECASE)

_FIELDS = ",".join([
    "paperId",
    "externalIds",
    "url",
    "title",
    "abstract",
    "authors",
    "year",
    "publicationDate",
    "citationCount",
    "influentialCitationCount",
    "tldr",
    "venue",
    "publicationVenue",
    "fieldsOfStudy",
    "openAccessPdf",
])


def _parse_qualifiers(query: str) -> tuple[str, dict]:
    kwargs: dict = {}
    m = _YEAR_RE.search(query)
    if m:
        kwargs["year"] = m.group(1)
        query = _YEAR_RE.sub(" ", query)
    m = _VENUE_RE.search(query)
    if m:
        kwargs["venue"] = m.group(1)
        query = _VENUE_RE.sub(" ", query)
    m = _MINCITE_RE.search(query)
    if m:
        kwargs["minCitationCount"] = int(m.group(1))
        query = _MINCITE_RE.sub(" ", query)
    return query.strip(), kwargs


def _headers() -> dict:
    key = os.environ.get("S2_API_KEY", "").strip()
    h = {"User-Agent": "omniseek/0.1 (research retrieval)"}
    if key:
        h["x-api-key"] = key
    return h


def _http_get(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=_headers())
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"semantic_scholar.http_error: {exc}", file=sys.stderr)
        return None


def _doc_from_paper(p: dict) -> dict:
    authors = []
    for a in p.get("authors") or []:
        nm = a.get("name")
        if nm:
            authors.append(nm)
    external = p.get("externalIds") or {}
    tldr_obj = p.get("tldr") or {}
    oa = p.get("openAccessPdf") or {}

    pub_date = p.get("publicationDate")
    fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "source": "semantic_scholar",
        "source_id": p.get("paperId") or "",
        "title": (p.get("title") or "").strip(),
        "url": p.get("url") or (f"https://www.semanticscholar.org/paper/{p.get('paperId')}" if p.get("paperId") else ""),
        "content": p.get("abstract") or (tldr_obj.get("text") if tldr_obj else None) or "",
        "authors": authors,
        "published_at": (pub_date + "T00:00:00Z") if pub_date else None,
        "fetched_at": fetched_at,
        "metadata": {
            "doi": external.get("DOI"),
            "arxiv_id": external.get("ArXiv"),
            "venue": (p.get("publicationVenue") or {}).get("name") if isinstance(p.get("publicationVenue"), dict) else p.get("venue"),
            "year": p.get("year"),
            "citation_count": p.get("citationCount"),
            "influential_citation_count": p.get("influentialCitationCount"),
            "fields_of_study": p.get("fieldsOfStudy") or [],
            "tldr": tldr_obj.get("text") if tldr_obj else None,
            "open_access_pdf_url": oa.get("url") if isinstance(oa, dict) else None,
        },
    }


def search(query: str, limit: int = 10) -> list[dict]:
    clean_query, qualifiers = _parse_qualifiers(query)
    params = {
        "query": clean_query,
        "limit": str(min(limit, 100)),
        "fields": _FIELDS,
    }
    for k, v in qualifiers.items():
        params[k] = v
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    data = _http_get(url)
    if not data:
        return []
    return [_doc_from_paper(p) for p in (data.get("data") or [])]


def lookup(paper_id: str) -> dict | None:
    """Resolve a paper by S2 ID, DOI, arXiv ID, etc. Returns one Document or None."""
    url = f"{PAPER_ENDPOINT}/{urllib.parse.quote(paper_id, safe='/:.-')}?fields={_FIELDS}"
    data = _http_get(url)
    if not data:
        return None
    return _doc_from_paper(data)


def main() -> int:
    p = argparse.ArgumentParser(description="Semantic Scholar paper search")
    p.add_argument("query", help="Search query (supports year:, venue:, min_citations: qualifiers)")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--lookup", help="Fetch a single paper by S2 paperId / DOI / arXiv ID instead of searching")
    args = p.parse_args()

    if args.lookup:
        doc = lookup(args.lookup)
        if doc is None:
            json.dump([], sys.stdout)
        else:
            json.dump([doc], sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0

    docs = search(args.query, limit=args.limit)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())