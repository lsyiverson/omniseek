#!/usr/bin/env python3
"""Hacker News: tech news + threaded community discussion via Algolia search.

Algolia hosts HN's official search endpoint (well-documented, no auth). The
script pulls BOTH stories (the headline submission) AND comments (the actual
thread discussion) so a small ``--limit`` surfaces both layers.

Docs: https://hn.algolia.com/api
Endpoints used:
  GET /search?query=<q>&tags=story&hitsPerPage=<n>
  GET /search?query=<q>&tags=comment&hitsPerPage=<n>

Examples:
    python3 hackernews.py "transformer attention" --limit 10
    python3 hackernews.py "rust async" --tag story --limit 15
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://hn.algolia.com/api/v1"


def _http_get(url: str, timeout: int = 15) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omniseek-mavis/0.1 (research retrieval)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"hackernews.http_error: {exc}", file=sys.stderr)
        return None


def _iso(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return s


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _story_doc(hit: dict) -> dict:
    return {
        "source": "hackernews_story",
        "source_id": str(hit.get("objectID") or ""),
        "title": (hit.get("title") or "").strip(),
        "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
        "content": (hit.get("story_text") or "").strip(),
        "authors": [hit.get("author")] if hit.get("author") else [],
        "published_at": _iso(hit.get("created_at")),
        "fetched_at": _now(),
        "metadata": {
            "kind": "story",
            "points": hit.get("points"),
            "num_comments": hit.get("num_comments"),
            "tags": hit.get("_tags") or [],
        },
    }


def _comment_doc(hit: dict) -> dict:
    return {
        "source": "hackernews_comment",
        "source_id": str(hit.get("objectID") or ""),
        "title": f"comment on: {hit.get('story_title') or hit.get('story_id')}",
        "url": f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
        "content": (hit.get("comment_text") or "").strip(),
        "authors": [hit.get("author")] if hit.get("author") else [],
        "published_at": _iso(hit.get("created_at")),
        "fetched_at": _now(),
        "metadata": {
            "kind": "comment",
            "story_id": hit.get("story_id"),
            "story_title": hit.get("story_title"),
            "story_url": hit.get("story_url"),
            "parent_id": hit.get("parent_id"),
            "tags": hit.get("_tags") or [],
        },
    }


def search(query: str, limit: int = 10, tags: str = "all") -> list[dict]:
    story_budget = max(1, (limit + 1) // 2)
    comment_budget = max(1, limit - story_budget)
    docs: list[dict] = []

    if tags in ("all", "story"):
        data = _http_get(f"{BASE}/search?query={urllib.parse.quote(query)}&tags=story&hitsPerPage={min(story_budget, 30)}")
        for hit in (data or {}).get("hits", [])[:story_budget]:
            docs.append(_story_doc(hit))

    if tags in ("all", "comment"):
        data = _http_get(f"{BASE}/search?query={urllib.parse.quote(query)}&tags=comment&hitsPerPage={min(comment_budget, 30)}")
        for hit in (data or {}).get("hits", [])[:comment_budget]:
            docs.append(_comment_doc(hit))

    return docs


def main() -> int:
    p = argparse.ArgumentParser(description="Hacker News tech news + community discussion search")
    p.add_argument("query", help="Free-text query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--tag", default="all", choices=["all", "story", "comment"], help="Which layer to query")
    args = p.parse_args()

    docs = search(args.query, limit=args.limit, tags=args.tag)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())