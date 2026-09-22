#!/usr/bin/env python3
"""Source catalog browser — list every source this skill can call.

Prints the full source inventory grouped by domain. Use to ROUTE: pick the
right source(s) before fanning out, or to discover what sources exist.

Examples:
    python3 catalog.py                       # full inventory, grouped by domain
    python3 catalog.py --domain papers       # only papers
    python3 catalog.py --source arxiv --describe   # detailed blurb for one source
    python3 catalog.py --json                # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys

CATALOG: dict[str, list[dict]] = {
    "papers": [
        {"name": "arxiv", "tier": "free", "script": "arxiv.py",
         "description": "arXiv preprints (export.arxiv.org/api/query; 1 req/3s polite rate)"},
        {"name": "openalex", "tier": "free", "script": "openalex.py",
         "description": "OpenAlex: 250M+ scholarly works (api.openalex.org; full-text + filters; faster lane with mailto:)"},
        {"name": "semantic_scholar", "tier": "free", "script": "semantic_scholar.py",
         "description": "Semantic Scholar: 225M+ papers, citation graphs, TLDRs (graph/v1/paper/search; optional S2_API_KEY)"},
        {"name": "crossref", "tier": "free", "script": "crossref.py",
         "description": "Crossref: ~150M formally-published DOI records (api.crossref.org/works; mailto: for fast lane)"},
        {"name": "dblp", "tier": "free", "script": "dblp.py",
         "description": "DBLP: CS bibliography (dblp.org/search/publ/api; canonical CS venue/year/DOI index)"},
        {"name": "europe_pmc", "tier": "free", "script": "europe_pmc.py",
         "description": "Europe PMC: ~40M biomedical abstracts + OA full text (ebi.ac.uk/europepmc/webservices/rest/search)"},
        {"name": "zenodo", "tier": "free", "script": "zenodo.py",
         "description": "Zenodo: open research repository with DOIs (zenodo.org/api/records)"},
    ],
    "code": [
        {"name": "github", "tier": "free", "script": "github.py",
         "description": "GitHub: code search + issues/PRs + discussions + repo activity (api.github.com; GITHUB_TOKEN for higher rate)"},
        {"name": "hf_daily_papers", "tier": "free", "script": "hf_daily_papers.py",
         "description": "Hugging Face Daily Papers: community-curated ML papers with upvotes (huggingface.co/api/daily-papers)"},
    ],
    "community": [
        {"name": "hackernews", "tier": "free", "script": "hackernews.py",
         "description": "Hacker News: tech news + threaded discussion (hn.algolia.com/api/v1/search)"},
        {"name": "stackoverflow", "tier": "free", "script": "stackoverflow.py",
         "description": "Stack Overflow: programming Q&A (api.stackexchange.com/2.3; 10k/day unauth)"},
        {"name": "reddit", "tier": "free", "script": "reddit.py",
         "description": "Reddit: general topic search via Arctic Shift mirror (arctic-shift.com/api/posts/search)"},
        {"name": "bluesky", "tier": "free", "script": "bluesky.py",
         "description": "Bluesky: public AT Protocol post search (public.api.bsky.app/xrpc/app.bsky.feed.searchPosts)"},
    ],
    "news": [
        {"name": "rss", "tier": "free", "script": "rss.py",
         "description": "Generic RSS/Atom aggregator (you supply feed URLs; useful for labs, journals, gov authorities)"},
        {"name": "smzdm", "tier": "free", "script": "smzdm.py",
         "description": "什么值得买 值客原创 RSS — Chinese consumer-product reviews & guides (post.smzdm.com/feed; no auth; keyword is post-fetch filter)"},
        {"name": "wayback", "tier": "free", "script": "wayback.py",
         "description": "Wayback Machine: snapshot history for a URL (web.archive.org/cdx/search/cdx)"},
    ],
    "jobs": [
        {"name": "mycareersfuture", "tier": "free", "script": "mycareersfuture.py",
         "description": "MyCareersFuture: SG government job board with mandatory salary ranges (api.mycareersfuture.gov.sg/v2/jobs)"},
        {"name": "remotive", "tier": "free", "script": "remotive.py",
         "description": "Remotive: curated REMOTE job board (remotive.com/api/remote-jobs; rate-limited, low-frequency drill)"},
    ],
    "funding": [
        {"name": "nsf_awards", "tier": "free", "script": "nsf_awards.py",
         "description": "NSF Award Search: US NSF research grants (api.nsf.gov/services/v1/awards.json)"},
        {"name": "nih_reporter", "tier": "free", "script": "nih_reporter.py",
         "description": "NIH RePORTER: US NIH biomedical research grants (api.reporter.nih.gov/v2/projects/search)"},
    ],
    "walled": [
        {"name": "walled_health", "tier": "free", "script": "walled_health.py",
         "description": "Probe the four CDP ports — is each Chrome up + logged in?"},
        {"name": "zhihu", "tier": "walled", "script": "walled/zhihu.py",
         "description": "知乎 search — REQUIRES playwright + a logged-in Chrome on port 9222 (run scripts/launch_browser.sh 9222)"},
        {"name": "nga", "tier": "walled", "script": "walled/nga.py",
         "description": "NGA玩家社区 (bbs.nga.cn) forum search + thread reader — port 9222; search needs a logged-in NGA account, reading most boards does too. Search mode: positional query (--fid board scope, --in-post full text). Read mode: --read TID / --read-url / --read-file"},
        {"name": "xiaohongshu", "tier": "walled", "script": "walled/xiaohongshu_search.py",
         "description": "小红书 discovery search — REQUIRES playwright + a logged-in Chrome on port 9223 (run scripts/launch_browser.sh 9223)"},
        {"name": "xiaohongshu_read", "tier": "walled", "script": "walled/xiaohongshu_read.py",
         "description": "小红书 note detail reader (body + comments) — port 9223; URLs MUST carry xsec_token (use xiaohongshu_search output)"},
        {"name": "smzdm_read", "tier": "walled", "script": "walled/smzdm_read.py",
         "description": "什么值得买 post detail (body + comments + engagement) — port 9226; needs a real Chrome to pass the fingerprint probe (no smzdm login required)"},
    ],
}


def list_catalog(domain: str | None = None) -> dict[str, list[dict]]:
    if domain:
        return {domain: CATALOG.get(domain, [])}
    return CATALOG


def describe(name: str) -> dict | None:
    for sources in CATALOG.values():
        for s in sources:
            if s["name"] == name:
                return s
    return None


def main() -> int:
    p = argparse.ArgumentParser(description="OmniSeek source catalog browser")
    p.add_argument("--domain", choices=list(CATALOG.keys()), help="Restrict to one domain")
    p.add_argument("--source", help="Print details for a single source")
    p.add_argument("--describe", action="store_true", help="With --source, print the full blurb")
    p.add_argument("--json", action="store_true", help="Machine-readable JSON")
    args = p.parse_args()

    if args.source:
        info = describe(args.source)
        if info is None:
            print(f"Unknown source: {args.source}", file=sys.stderr)
            return 1
        if args.json:
            json.dump(info, sys.stdout, indent=2, ensure_ascii=False)
            print()
        else:
            print(f"\n[{info['name']}]  tier={info['tier']}  script={info['script']}")
            if args.describe:
                print(f"  {info['description']}\n")
        return 0

    catalog = list_catalog(args.domain)
    if args.json:
        json.dump(catalog, sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        for domain, sources in catalog.items():
            print(f"\n[{domain}]  ({len(sources)} sources)")
            for s in sources:
                tag = f" [{s['tier']}]" if s["tier"] != "free" else ""
                print(f"  - {s['name']}{tag}  →  python3 scripts/{s['script']}")
                if args.describe:
                    print(f"      {s['description']}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
