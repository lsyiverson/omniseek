#!/usr/bin/env python3
"""DBLP: Computer Science bibliography (~7M publications, canonical CS lens).

Keyless XML API. DBLP is the canonical CS venue/year/DOI index — for any CS
paper not on arxiv (especially formal-venue papers, older works, conference
proceedings), DBLP has the cleanest record.

Docs: https://dblp.org/xml/
Endpoints:
  GET https://dblp.org/search/publ/api?q=<query>&format=json&h=<n>
  GET https://dblp.org/search/author/api?q=<query>&format=json&h=<n>

Examples:
    python3 dblp.py "transformer attention" --limit 5
    python3 dblp.py "au:yoshua bengio" --limit 5
    python3 dblp.py "venue:NeurIPS 2024 diffusion" --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://dblp.org/search/publ/api"
AUTHOR_ENDPOINT = "https://dblp.org/search/author/api"


def _http_get(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omniseek-mavis/0.1 (research retrieval)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"dblp.http_error: {exc}", file=sys.stderr)
        return None


def _doc_from_hit(hit: dict) -> dict:
    info = hit.get("info") or {}
    authors = []
    for a in info.get("authors", {}).get("author", []) or []:
        nm = a.get("text") if isinstance(a, dict) else a
        if nm:
            authors.append(nm)

    venue = info.get("venue")
    year = info.get("year")
    pub_date = f"{year}-01-01T00:00:00Z" if year and str(year).isdigit() else None

    fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "source": "dblp",
        "source_id": info.get("key") or info.get("doi") or "",
        "title": (info.get("title") or "").strip(),
        "url": info.get("url") or info.get("ee") or "",
        "content": "",  # DBLP doesn't carry abstracts; the linked page may
        "authors": authors,
        "published_at": pub_date,
        "fetched_at": fetched_at,
        "metadata": {
            "venue": venue,
            "year": year,
            "type": info.get("type"),
            "doi": info.get("doi"),
            "volume": info.get("volume"),
            "pages": info.get("pages"),
            "ee": (info.get("ee") or ""),
            "publisher": info.get("publisher"),
        },
    }


def search(query: str, limit: int = 10) -> list[dict]:
    params = {
        "q": query,
        "format": "json",
        "h": str(min(limit, 50)),
    }
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    data = _http_get(url)
    if not data:
        return []
    hits = ((data.get("result") or {}).get("hits") or {}).get("hit") or []
    return [_doc_from_hit(h) for h in hits]


def search_author(query: str, limit: int = 10) -> list[dict]:
    """Lookup authors (use this when the query is about a person, not a paper)."""
    params = {
        "q": query,
        "format": "json",
        "h": str(min(limit, 50)),
    }
    url = f"{AUTHOR_ENDPOINT}?{urllib.parse.urlencode(params)}"
    data = _http_get(url)
    if not data:
        return []
    hits = ((data.get("result") or {}).get("hits") or {}).get("hit") or []
    return [
        {
            "source": "dblp_author",
            "source_id": (h.get("info") or {}).get("url") or "",
            "title": (h.get("info") or {}).get("author") or "",
            "url": (h.get("info") or {}).get("url") or "",
            "content": "",
            "authors": [(h.get("info") or {}).get("author") or ""],
            "published_at": None,
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "metadata": {
                "affiliation": ((h.get("info") or {}).get("notes") or {}).get("note"),
                "paper_count": (h.get("info") or {}).get("n", 0),
            },
        }
        for h in hits
    ]


def main() -> int:
    p = argparse.ArgumentParser(description="DBLP publication / author search")
    p.add_argument("query", help="Search query (DBLP native syntax: au:, venue:, ti:, year:)")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--author", action="store_true", help="Search for an author profile instead of publications")
    args = p.parse_args()

    fn = search_author if args.author else search
    docs = fn(args.query, limit=args.limit)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())