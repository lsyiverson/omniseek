#!/usr/bin/env python3
"""Remotive: curated REMOTE job board (keyless public API).

Curated by Remotive.io — taxonomy of categories, candidate-required-location,
job type, salary, tags. Rate-limited (a few calls/day): use as a low-frequency
drill, not a hot path.

Docs: https://remotive.com/api-documentation
Endpoint: GET https://remotive.com/api/remote-jobs?search=<q>&limit=<n>

Examples:
    python3 remotive.py "machine learning" --limit 20
    python3 remotive.py "" --category software-dev --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://remotive.com/api/remote-jobs"


def _http_get(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omniseek/0.1 (research retrieval)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"remotive.http_error: {exc}", file=sys.stderr)
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


def _doc_from_job(j: dict) -> dict:
    return {
        "source": "remotive",
        "source_id": str(j.get("id") or ""),
        "title": (j.get("title") or "").strip(),
        "url": j.get("url") or "",
        "content": (j.get("description") or "")[:3000],
        "authors": [(j.get("company_name") or "")] if j.get("company_name") else [],
        "published_at": _iso(j.get("publication_date")),
        "fetched_at": _now(),
        "metadata": {
            "company": j.get("company_name"),
            "company_logo": j.get("company_logo"),
            "category": j.get("category"),
            "tags": j.get("tags") or [],
            "job_type": j.get("job_type"),
            "candidate_required_location": j.get("candidate_required_location"),
            "salary": j.get("salary"),
            "apply_url": j.get("url"),
        },
    }


def search(query: str, limit: int = 10, category: str | None = None) -> list[dict]:
    params = {"limit": str(min(limit, 50))}
    if query:
        params["search"] = query
    if category:
        params["category"] = category
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    data = _http_get(url)
    if not isinstance(data, dict):
        return []
    return [_doc_from_job(j) for j in (data.get("jobs") or [])]


def main() -> int:
    p = argparse.ArgumentParser(description="Remotive remote job board")
    p.add_argument("query", help="Role keyword (or empty string to browse)")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--category", help="Remotive category, e.g. software-dev, data-science")
    args = p.parse_args()

    docs = search(args.query, limit=args.limit, category=args.category)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())