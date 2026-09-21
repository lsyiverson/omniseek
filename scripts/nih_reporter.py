#!/usr/bin/env python3
"""NIH RePORTER: US NIH biomedical research grants.

Free public POST API. Returns structured award data: contact PI, organization,
total cost, full abstract, project terms, public health relevance.

Docs: https://api.reporter.nih.gov/
Endpoint: POST https://api.reporter.nih.gov/v2/projects/search

Examples:
    python3 nih_reporter.py "clinical NLP" --limit 10
    python3 nih_reporter.py "lung cancer immunotherapy" --fiscal-year 2025 --limit 20
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://api.reporter.nih.gov/v2/projects/search"


def _http_post(url: str, payload: dict, timeout: int = 30) -> dict | None:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "User-Agent": "omniseek-mavis/0.1 (research retrieval)",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        print(f"nih_reporter.http_error: {exc.code}: {body[:300]}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"nih_reporter.http_error: {exc}", file=sys.stderr)
        return None


def _doc_from_project(p: dict) -> dict:
    org = p.get("organization") or {}
    pi_list = p.get("principal_investigators") or []
    pi = None
    if pi_list:
        first = pi_list[0]
        pi = (first.get("full_name") or "").strip() or f"{first.get('first_name', '')} {first.get('last_name', '')}".strip()

    project_num = p.get("project_num") or ""
    start = p.get("project_start_date")
    end = p.get("project_end_date")

    return {
        "source": "nih_reporter",
        "source_id": project_num,
        "title": (p.get("project_title") or "").strip(),
        "url": f"https://reporter.nih.gov/project-details/{project_num}" if project_num else "",
        "content": (p.get("abstract_text") or "").strip(),
        "authors": [pi] if pi else [],
        "published_at": (start + "T00:00:00Z") if start else None,
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "metadata": {
            "project_num": project_num,
            "activity_type": (p.get("activity_type") or "").strip() if isinstance(p.get("activity_type"), str) else p.get("activity_type"),
            "award_type": (p.get("award_type") or "").strip() if isinstance(p.get("award_type"), str) else p.get("award_type"),
            "fiscal_year": p.get("fiscal_year"),
            "organization": org.get("name"),
            "org_city": org.get("city"),
            "org_state": org.get("state"),
            "org_country": org.get("country"),
            "total_cost": (p.get("award_amount") or {}).get("total_cost"),
            "total_cost_currency": "USD",
            "direct_cost": (p.get("award_amount") or {}).get("direct_cost"),
            "indirect_cost": (p.get("award_amount") or {}).get("indirect_cost"),
            "pi_last_name": (pi_list[0] if pi_list else {}).get("last_name") if pi_list else None,
            "pi_first_name": (pi_list[0] if pi_list else {}).get("first_name") if pi_list else None,
            "pi_full_name": pi,
            "project_start_date": start,
            "project_end_date": end,
            "organization_type": org.get("org_type"),
            "program_officers": [
                po.get("full_name") for po in (p.get("program_officers") or [])
                if isinstance(po, dict) and po.get("full_name")
            ],
            "phr_text": (p.get("phr_text") or "")[:1000],
        },
    }


def search(keyword: str, limit: int = 10, fiscal_year: int | None = None) -> list[dict]:
    payload = {
        "criteria": {
            "advanced_text_search": {
                "operator": "and",
                "search_field": "projecttitle,abstracttext,terms",
                "search_text": keyword,
            }
        },
        "limit": min(limit, 50),
        "offset": 0,
        "sort_field": "fiscal_year",
        "sort_order": "desc",
    }
    if fiscal_year:
        payload["criteria"]["fiscal_years"] = [fiscal_year]

    data = _http_post(ENDPOINT, payload)
    if not isinstance(data, dict):
        return []
    return [_doc_from_project(p) for p in (data.get("results") or [])]


def main() -> int:
    p = argparse.ArgumentParser(description="NIH RePORTER — US NIH biomedical research grants")
    p.add_argument("keyword", help="Free-text keyword searched against title/abstract/terms")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--fiscal-year", type=int, help="Single fiscal year filter (e.g. 2025)")
    args = p.parse_args()

    docs = search(args.keyword, limit=args.limit, fiscal_year=args.fiscal_year)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())