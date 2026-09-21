#!/usr/bin/env python3
"""Crossref: DOI registration agency (~150M formally published works).

Complement to arxiv (preprints), openalex (open graph), and semantic_scholar
(citation graph + TLDRs). Crossref's strength is formal publisher metadata,
DOIs, and bibliographic records.

Docs: https://api.crossref.org/swagger-ui/index.html
Endpoint: GET /works?query=<q>&rows=<n>

Polite-pool: include ``mailto=`` in User-Agent for the fast lane. The script
reads it from the ``OMNISEEK_CONTACT_EMAIL`` env var if set.

Examples:
    python3 crossref.py "transformer attention" --limit 5
    python3 crossref.py "10.1038/nature12373" --doi
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://api.crossref.org/works"


def _ua() -> str:
    mailto = os.environ.get("OMNISEEK_CONTACT_EMAIL") or ""
    if mailto:
        return f"omniseek-mavis/0.1 (mailto:{mailto}; research retrieval)"
    return "omniseek-mavis/0.1 (research retrieval)"


def _http_get(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _ua()})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"crossref.http_error: {exc}", file=sys.stderr)
        return None


def _authors(item: dict) -> list[str]:
    out = []
    for a in item.get("author") or []:
        nm = a.get("name") or f"{a.get('given', '')} {a.get('family', '')}".strip()
        if nm:
            out.append(nm)
    return out


def _doc_from_item(item: dict) -> dict:
    title_list = item.get("title") or []
    title = (title_list[0] if title_list else "").strip()
    abstract = (item.get("abstract") or "").strip()
    # Strip basic JATS XML tags from abstract if present
    abstract = re.sub(r"<[^>]+>", "", abstract) if abstract else ""

    container = (item.get("container-title") or [])
    venue = container[0] if container else None

    issued = (item.get("issued") or {}).get("date-parts") or []
    pub_date = None
    if issued and issued[0]:
        parts = issued[0]
        y = parts[0] if len(parts) > 0 else None
        m = parts[1] if len(parts) > 1 else 1
        d = parts[2] if len(parts) > 2 else 1
        if y:
            pub_date = f"{y:04d}-{m:02d}-{d:02d}T00:00:00Z"

    doi = (item.get("DOI") or "").strip() or None
    url = item.get("URL") or (f"https://doi.org/{doi}" if doi else "")

    fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "source": "crossref",
        "source_id": doi or (item.get("URL") or ""),
        "title": title or "(untitled)",
        "url": url,
        "content": abstract,
        "authors": _authors(item),
        "published_at": pub_date,
        "fetched_at": fetched_at,
        "metadata": {
            "doi": doi,
            "venue": venue,
            "type": item.get("type"),
            "publisher": item.get("publisher"),
            "is_referenced_by_count": item.get("is-referenced-by-count"),
            "references_count": item.get("references-count"),
            "subject": [s for s in (item.get("subject") or [])][:5],
            "license": (item.get("license") or [{}])[0].get("URL") if item.get("license") else None,
            "issn": item.get("ISSN"),
            "isbn": item.get("ISBN"),
        },
    }


import re


def search(query: str, limit: int = 10) -> list[dict]:
    params = {"query": query, "rows": str(min(limit, 50))}
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    data = _http_get(url)
    if not data:
        return []
    items = ((data.get("message") or {}).get("items")) or []
    return [_doc_from_item(it) for it in items]


def fetch_doi(doi: str) -> dict | None:
    url = f"{ENDPOINT}/{urllib.parse.quote(doi, safe='/')}"
    data = _http_get(url)
    if not data:
        return None
    item = (data.get("message") or {})
    if not item:
        return None
    return _doc_from_item(item)


def main() -> int:
    p = argparse.ArgumentParser(description="Crossref DOI/works search")
    p.add_argument("query", help="Free-text search or a DOI if --doi is passed")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--doi", action="store_true", help="Treat the query as a DOI and fetch it directly")
    args = p.parse_args()

    if args.doi:
        doc = fetch_doi(args.query)
        json.dump([doc] if doc else [], sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0

    docs = search(args.query, limit=args.limit)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())