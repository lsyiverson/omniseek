#!/usr/bin/env python3
"""NSF Award Search: US National Science Foundation research grants.

Free public API. Returns structured award data: PI, awardee organization,
amount, full abstract, program, start date.

Docs: https://www.nsf.gov/developer
Endpoint: GET https://api.nsf.gov/services/v1/awards.json?keyword=<q>&rpp=<n>

Examples:
    python3 nsf_awards.py "machine learning" --limit 10
    python3 nsf_awards.py "alignment interpretability" --pi "Yoshua Bengio" --limit 20
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://api.nsf.gov/services/v1/awards.json"


def _http_get(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omniseek/0.1 (research retrieval)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"nsf_awards.http_error: {exc}", file=sys.stderr)
        return None


def _doc_from_award(a: dict) -> dict:
    pi = a.get("piFirstName", "") + " " + a.get("piLastName", "")
    pi = pi.strip()

    start_iso = None
    if a.get("startDate"):
        start_iso = a["startDate"] + "T00:00:00Z"
    end_iso = None
    if a.get("expDate"):
        end_iso = a["expDate"] + "T00:00:00Z"

    return {
        "source": "nsf_awards",
        "source_id": a.get("id") or a.get("awardNumber") or "",
        "title": (a.get("title") or "").strip(),
        "url": f"https://www.nsf.gov/awardsearch/showAward?AWD_ID={a.get('id')}" if a.get("id") else "",
        "content": (a.get("abstractText") or "").strip(),
        "authors": [pi] if pi else [],
        "published_at": start_iso,
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "metadata": {
            "award_id": a.get("id"),
            "pi_first_name": a.get("piFirstName"),
            "pi_last_name": a.get("piLastName"),
            "pi_email": a.get("piEmail"),
            "awardee_name": a.get("awardeeName"),
            "awardee_city": a.get("awardeeCity"),
            "awardee_state": a.get("awardeeStateCode"),
            "awardee_country": a.get("awardeeCountryCode"),
            "date": start_iso,
            "exp_date": end_iso,
            "amount": a.get("amount"),
            "currency": "USD",
            "fund_program_name": a.get("fundProgramName"),
            "directorate": a.get("directorate"),
            "division": a.get("division"),
            "program_officer": a.get("programOfficer"),
            "co_pd_pi_flag": a.get("coPDPI"),
        },
    }


def search(keyword: str, pi: str | None = None, limit: int = 10) -> list[dict]:
    params = {"keyword": keyword, "rpp": str(min(limit, 50))}
    if pi:
        params["piLastName"] = pi.split()[-1] if pi else pi
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    data = _http_get(url)
    if not isinstance(data, dict):
        return []
    awards = (data.get("response") or {}).get("award") or []
    return [_doc_from_award(a) for a in awards]


def main() -> int:
    p = argparse.ArgumentParser(description="NSF Award Search — US NSF research grants")
    p.add_argument("keyword", help="Keyword to search in award title/abstract")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--pi", help="Optional PI last name filter")
    args = p.parse_args()

    docs = search(args.keyword, pi=args.pi, limit=args.limit)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())