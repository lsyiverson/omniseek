#!/usr/bin/env python3
"""Europe PMC: biomedical / life-sciences literature with keyless full text.

Europe PMC (EMBL-EBI) indexes ~40M abstracts plus a large open-access full-text
corpus (PMC articles, Agricola, preprints, patents, theses). Public REST API,
no auth, no key. This is the SECOND keyless full-text spine alongside CORE
(which needs a registered key).

Docs: https://europepmc.org/RestfulWebService
Endpoint: GET https://www.ebi.ac.uk/europepmc/webservices/rest/search
          ?query=<q>&format=json&resultType=core&pageSize=<n>

Examples:
    python3 europe_pmc.py "CRISPR off-target effects" --limit 5
    python3 europe_pmc.py "OPEN_ACCESS:Y AND machine learning radiology" --limit 5
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def _http_get(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omniseek-mavis/0.1 (research retrieval)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"europe_pmc.http_error: {exc}", file=sys.stderr)
        return None


def _authors(author_string: str | None) -> list[str]:
    if not author_string:
        return []
    return [a.strip() for a in re.split(r"[,;]", author_string) if a.strip()]


def _doc_from_result(r: dict) -> dict:
    title = (r.get("title") or "").strip()
    abstract = (r.get("abstractText") or "").strip()
    authors = _authors(r.get("authorString"))

    first_pub = r.get("firstPublicationDate")
    fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pmcid = r.get("pmcid")
    doi = r.get("doi")
    source = r.get("source")  # MED, PMC, AGRICOLA, etc.
    rid = r.get("id")

    url = None
    if doi:
        url = f"https://doi.org/{doi}"
    elif pmcid:
        url = f"https://europepmc.org/article/PMC/{pmcid}"
    elif rid and source:
        url = f"https://europepmc.org/article/{source}/{rid}"

    return {
        "source": "europe_pmc",
        "source_id": rid or doi or "",
        "title": title or "(untitled)",
        "url": url or "",
        "content": abstract,
        "authors": authors,
        "published_at": (first_pub + "T00:00:00Z") if first_pub else None,
        "fetched_at": fetched_at,
        "metadata": {
            "pmcid": pmcid,
            "pmid": r.get("pmid"),
            "doi": doi,
            "source_db": source,
            "is_open_access": r.get("isOpenAccess") == "Y",
            "in_epmc": r.get("inEPMC") == "Y",
            "has_pdf": r.get("hasPDF") == "Y",
            "cited_by_count": r.get("citedByCount"),
            "journal_title": r.get("journalTitle"),
            "journal_volume": r.get("journalVolume"),
            "journal_issue": r.get("journalIssue"),
            "page_info": r.get("pageInfo"),
            "pub_types": [p.get("label") for p in (r.get("pubTypeList") or {}).get("pubType", [])],
            "language": r.get("language"),
        },
    }


def search(query: str, limit: int = 10) -> list[dict]:
    params = {
        "query": query,
        "format": "json",
        "resultType": "core",
        "pageSize": str(min(limit, 50)),
    }
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    data = _http_get(url)
    if not data:
        return []
    results = ((data.get("resultList") or {}).get("result")) or []
    return [_doc_from_result(r) for r in results]


def main() -> int:
    p = argparse.ArgumentParser(description="Europe PMC biomedical literature search")
    p.add_argument("query", help="Free-text query (supports Europe PMC syntax: OPEN_ACCESS:Y, HAS_PDF:Y, etc.)")
    p.add_argument("--limit", type=int, default=10)
    args = p.parse_args()

    docs = search(args.query, limit=args.limit)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())