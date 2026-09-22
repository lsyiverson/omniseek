#!/usr/bin/env python3
"""Zenodo: open research repository (papers, datasets, software, theses) with DOIs.

General-purpose open repository backed by CERN. Every deposit gets a DOI.
Useful for: datasets, software releases, conference papers, theses, reports —
things that often don't appear on arxiv or in publisher databases.

Docs: https://developers.zenodo.org
Endpoint: GET https://zenodo.org/api/records?q=<query>&size=<n>

Examples:
    python3 zenodo.py "transformer attention" --limit 5
    python3 zenodo.py "type:dataset AND ml" --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://zenodo.org/api/records"


def _http_get(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omniseek/0.1 (research retrieval)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"zenodo.http_error: {exc}", file=sys.stderr)
        return None


def _doc_from_hit(h: dict) -> dict:
    md = h.get("metadata") or {}
    title = (md.get("title") or "").strip()
    abstract = (md.get("abstract") or "").strip() or (md.get("description") or "").strip()

    creators = []
    for c in md.get("creators") or []:
        nm = c.get("name") or f"{c.get('givenname', '')} {c.get('familyname', '')}".strip()
        if nm:
            creators.append(nm)

    pub_date = md.get("publication_date")
    fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    resource_type = md.get("resource_type") or {}
    communities = [c.get("id") for c in md.get("communities") or []]

    doi = md.get("doi")
    return {
        "source": "zenodo",
        "source_id": str(h.get("id") or doi or ""),
        "title": title or "(untitled)",
        "url": (h.get("links") or {}).get("self_html") or (f"https://doi.org/{doi}" if doi else ""),
        "content": abstract,
        "authors": creators,
        "published_at": (pub_date + "T00:00:00Z") if pub_date else None,
        "fetched_at": fetched_at,
        "metadata": {
            "doi": doi,
            "resource_type": resource_type.get("type"),
            "resource_subtype": resource_type.get("subtype"),
            "communities": communities,
            "access_right": (md.get("access_right") or ""),
            "license": ((md.get("license") or {}).get("id") if isinstance(md.get("license"), dict) else md.get("license")),
            "version": md.get("version"),
            "keywords": [k.get("term") for k in (md.get("keywords") or []) if isinstance(k, dict) and k.get("term")],
            "files_count": len(h.get("files") or []),
            "downloads": h.get("stats", {}).get("downloads"),
            "views": h.get("stats", {}).get("views"),
            "citation_count": h.get("stats", {}).get("citations"),
        },
    }


def search(query: str, limit: int = 10) -> list[dict]:
    params = {"q": query, "size": str(min(limit, 50))}
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    data = _http_get(url)
    if not data:
        return []
    hits = (h.get("hits") or {}).get("hits") or []
    return [_doc_from_hit(h) for h in hits]


def main() -> int:
    p = argparse.ArgumentParser(description="Zenodo open research repository search")
    p.add_argument("query", help="Free-text query (Zenodo supports type:, subtype:, etc.)")
    p.add_argument("--limit", type=int, default=10)
    args = p.parse_args()

    docs = search(args.query, limit=args.limit)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())