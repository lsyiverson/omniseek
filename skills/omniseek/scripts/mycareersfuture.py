#!/usr/bin/env python3
"""MyCareersFuture: Singapore government job board with mandatory salary ranges.

Singapore's official jobs platform. Every posting MUST include a salary range
+ the hiring company's UEN — making this a uniquely transparent job source
for the SG market.

Docs: https://documenter.getpostman.com/view/4687502/RW87T98s
Endpoint: GET https://api.mycareersfuture.gov.sg/v2/jobs?search=<q>&limit=<n>

Examples:
    python3 mycareersfuture.py "machine learning" --limit 10
    python3 mycareersfuture.py "data scientist" --limit 20 --employment permanent
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://api.mycareersfuture.gov.sg/v2/jobs"


def _http_get(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "omniseek-mavis/0.1 (research retrieval)",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"mycareersfuture.http_error: {exc}", file=sys.stderr)
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
    salary_min = (j.get("salary") or {}).get("minimum")
    salary_max = (j.get("salary") or {}).get("maximum")
    salary_type = (j.get("salary") or {}).get("type")

    addr = j.get("address") or {}
    posted = j.get("postedDate") or j.get("createdAt") or j.get("metadata", {}).get("createdAt")

    return {
        "source": "mycareersfuture",
        "source_id": j.get("uuid") or j.get("id") or "",
        "title": (j.get("title") or "").strip(),
        "url": j.get("metadata", {}).get("jobDetailsUrl") or "",
        "content": (j.get("description") or "")[:3000],
        "authors": [(j.get("postedCompany") or {}).get("name")] if j.get("postedCompany") else [],
        "published_at": _iso(posted),
        "fetched_at": _now(),
        "metadata": {
            "company": (j.get("postedCompany") or {}).get("name"),
            "uen": (j.get("postedCompany") or {}).get("uen"),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": "SGD",
            "salary_type": salary_type,
            "location": addr.get("label") or ", ".join(filter(None, [addr.get("city"), addr.get("country")])),
            "categories": [c.get("category") for c in (j.get("categories") or []) if isinstance(c, dict)],
            "employment_types": j.get("employmentTypes") or [],
            "position_levels": [p.get("position") for p in (j.get("positionLevels") or []) if isinstance(p, dict)],
        },
    }


def search(query: str, limit: int = 10, employment: str | None = None) -> list[dict]:
    params = {
        "search": query,
        "limit": str(min(limit, 30)),
        "page": "0",
    }
    if employment:
        params["employmentType"] = employment
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    data = _http_get(url)
    if not isinstance(data, dict):
        return []
    items = data.get("results") or data.get("jobs") or []
    return [_doc_from_job(j) for j in items]


def main() -> int:
    p = argparse.ArgumentParser(description="MyCareersFuture SG job board")
    p.add_argument("query", help="Role keyword, e.g. 'machine learning'")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--employment", choices=["permanent", "contract", "internship", "parttime", "temporary", "flex"], help="Employment type")
    args = p.parse_args()

    docs = search(args.query, limit=args.limit, employment=args.employment)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())