#!/usr/bin/env python3
"""Reddit: GENERAL topic search via the Arctic Shift public mirror.

Arctic Shift (https://github.com/ArthurHeitmann/arctic_shift) is a free
public mirror of Reddit's data. Reddit's own API is WAF-blocked from most
data-center IPs; Arctic Shift is the keyless workaround.

Docs: https://github.com/ArthurHeitmann/arctic_shift
Endpoint: GET https://arctic-shift.com/api/posts/search?query=<q>&limit=<n>&sort=<...>

Examples:
    python3 reddit.py "machine learning" --limit 20
    python3 reddit.py "PhD application" --subreddit PhD AskAcademia --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://arctic-shift.com/api/posts/search"


def _http_get(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omniseek-mavis/0.1 (research retrieval)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"reddit.http_error: {exc}", file=sys.stderr)
        return None


def _iso(s: str | int | None) -> str | None:
    if not s:
        return None
    try:
        v = float(s)
        if v > 1e11:  # milliseconds
            return datetime.fromtimestamp(v / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
        return datetime.fromtimestamp(v, timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _doc_from_post(p: dict) -> dict:
    return {
        "source": "reddit",
        "source_id": str(p.get("id") or p.get("name") or ""),
        "title": (p.get("title") or "").strip(),
        "url": (p.get("url") or "") if (p.get("url") or "").startswith("http") else f"https://www.reddit.com{p.get('permalink', '')}",
        "content": (p.get("selftext") or p.get("body") or "")[:3000],
        "authors": [p.get("author")] if p.get("author") else [],
        "published_at": _iso(p.get("created_utc")),
        "fetched_at": _now(),
        "metadata": {
            "subreddit": p.get("subreddit"),
            "score": p.get("score"),
            "num_comments": p.get("num_comments"),
            "permalink": p.get("permalink"),
            "is_self": p.get("is_self"),
            "link_flair_text": p.get("link_flair_text"),
        },
    }


def search(query: str, limit: int = 10, subreddit: str | None = None, sort: str = "relevance") -> list[dict]:
    params = {
        "query": query,
        "limit": str(min(limit, 50)),
        "sort": sort,
    }
    if subreddit:
        params["subreddit"] = subreddit
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    data = _http_get(url)
    if not isinstance(data, dict):
        return []
    items = data.get("data") or data.get("posts") or data.get("items") or []
    return [_doc_from_post(p) for p in items]


def main() -> int:
    p = argparse.ArgumentParser(description="Reddit search via Arctic Shift mirror")
    p.add_argument("query", help="Free-text search query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--subreddit", help="Restrict to a single subreddit")
    p.add_argument("--sort", default="relevance", choices=["relevance", "new", "top", "hot", "comments"])
    args = p.parse_args()

    docs = search(args.query, limit=args.limit, subreddit=args.subreddit, sort=args.sort)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())