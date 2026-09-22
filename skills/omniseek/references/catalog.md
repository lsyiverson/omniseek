# Catalog Reference — every source this skill ships

This is the curated source inventory baked into the OmniSeek skill. Each
script distills one adapter from the upstream
[`Battam1111/omniseek`](https://github.com/Battam1111/omniseek) repo into a
standalone CLI. See `sources-derived.md` for the per-script provenance.

Browse the live catalog from the shell:

```bash
python3 scripts/catalog.py                 # full inventory
python3 scripts/catalog.py --describe      # with one-line blurbs
python3 scripts/catalog.py --domain papers # one domain only
python3 scripts/catalog.py --source arxiv --describe  # one source
```

## Tier semantics

| Tier | Meaning |
|---|---|
| `free` | Keyless, public API or scrape. On by default. |
| `keyed` | Requires an API key (env var). On once the key is set. |
| `walled` | Requires a login / browser session. **Off by default**; never bundled in this skill. |

Every script in this skill is `free`. To extend with `keyed` or `walled`
sources, write new scripts following the same `Document` envelope spec in
`normalize.md` and add them to `scripts/catalog.py`.

## Domain: papers

| Source | Endpoint | Qualifiers | Rate |
|---|---|---|---|
| `arxiv` | `export.arxiv.org/api/query` | `ti:`, `au:`, `cat:`, `abs:`; `AND`/`OR`; `--year` | 1 req / 3 s |
| `openalex` | `api.openalex.org/works` | inline `key:value` (allowlist); `--type` | polite pool with `mailto:` |
| `semantic_scholar` | `api.semanticscholar.org/graph/v1/paper/search` | inline `year:`, `venue:`, `min_citations:` | 5000/5min; 1 RPS with `S2_API_KEY` |
| `crossref` | `api.crossref.org/works` | free-text; `--doi` to fetch by DOI | polite pool with `mailto:` |
| `dblp` | `dblp.org/search/publ/api` | `au:`, `venue:` | unbounded |
| `europe_pmc` | `ebi.ac.uk/europepmc/webservices/rest/search` | Europe PMC native (`OPEN_ACCESS:Y`, `HAS_PDF:Y`) | unbounded |
| `zenodo` | `zenodo.org/api/records` | free-text; embedded qualifiers `type:`, etc. | unbounded |

Paper-search "paper triangle" (covers ~95% of academic queries):

```bash
python3 scripts/multi_search.py "transformer attention" --sources arxiv,openalex,semantic_scholar --limit 5
```

For formal-venue / older CS papers add `dblp`. For biomedical, add
`europe_pmc`. For DOIs of formal publications, add `crossref`.

## Domain: code

| Source | Endpoint | Qualifiers | Rate |
|---|---|---|---|
| `github` | `api.github.com` (REST + GraphQL) | GitHub native: `org:`, `user:`, `language:`, `path:`, `is:`, `label:`, `state:`; `tree:owner/repo[@branch]`; `org:NAME` alone = newest repos | 60/h anonymous, 5000/h with `GITHUB_TOKEN` |
| `hf_daily_papers` | `huggingface.co/api/daily-papers` | `--date YYYY-MM-DD` (default: today + yesterday) | unbounded |

GitHub query routing:

- bare `org:NAME` / `user:NAME` → that owner's newest repos
- `tree:owner/repo` → file tree (path-only, no content)
- anything else → code + issues/PR fan-out, deduped

## Domain: community

| Source | Endpoint | Qualifiers | Rate |
|---|---|---|---|
| `hackernews` | `hn.algolia.com/api/v1/search` | free-text; `--tag story|comment|all` | unbounded |
| `stackoverflow` | `api.stackexchange.com/2.3/search/advanced` | free-text; `--tagged pytorch cuda` | 10000/day unauth |
| `reddit` | `arctic-shift.com/api/posts/search` | free-text; `--subreddit`; `--sort` | unbounded |
| `bluesky` | `public.api.bsky.app/xrpc/app.bsky.feed.searchPosts` | free-text; `--since 24h` | unbounded |

HN pulls BOTH stories and comments per call (default `--tag all`), budget
split 50/50. Use `--tag story` to focus on submissions or `--tag comment`
for thread-level matches.

## Domain: news

| Source | Endpoint | Qualifiers | Rate |
|---|---|---|---|
| `rss` | (your URLs) | positional URLs; `--file list.txt` | per-feed politeness |
| `smzdm` | `post.smzdm.com/feed` | `--keyword` `--category` `--limit` | commonly captcha-gated (fingerprint probe, not login); if `web_fetch`/RSS returns captcha, skip straight to `walled/smzdm_read.py` (port 9226) — no smzdm login needed |
| `wayback` | `web.archive.org/cdx/search/cdx` | positional URL; `--from` `--to` | unbounded |

`rss.py` is a generic aggregator — you supply feed URLs. Useful for lab
blogs, journal TOC feeds, conference news, immigration authority updates.
Way to build a custom feed list:

```bash
cat <<'EOF' > /tmp/feeds.txt
https://bair.berkeley.edu/blog/feed.xml
https://crfm.stanford.edu/feed.xml
https://blog.deepmind.com/rss.xml
https://export.arxiv.org/rss/cs.LG
EOF
python3 scripts/rss.py --file /tmp/feeds.txt --limit 5
```

## Domain: jobs

| Source | Endpoint | Qualifiers | Rate |
|---|---|---|---|
| `mycareersfuture` | `api.mycareersfuture.gov.sg/v2/jobs` | free-text; `--employment permanent\|contract\|internship\|parttime\|temporary\|flex` | unbounded |
| `remotive` | `remotive.com/api/remote-jobs` | free-text; `--category software-dev` | few calls/day (use as drill) |

MyCareersFuture is uniquely structured: every listing has a published
salary range + the company's UEN. Remotive is the curated REMOTE board;
treat it as a low-frequency drill, not a hot path.

## Domain: funding

| Source | Endpoint | Qualifiers | Rate |
|---|---|---|---|
| `nsf_awards` | `api.nsf.gov/services/v1/awards.json` | `--keyword`; `--pi` last name | unbounded |
| `nih_reporter` | `api.reporter.nih.gov/v2/projects/search` (POST) | `--keyword`; `--fiscal-year` | unbounded |

NSF + NIH are the two US federal science funders with public REST APIs.
Add EU CORDIS / UK UKRI / Canada NSERC / China NSFC for international
coverage — those need new scripts (see "Adding a source" below).

## Adding a new source

1. Write a new CLI script under `scripts/` that follows the `Document`
   envelope in `normalize.md` and prints a JSON list to stdout.
2. Add an entry to the `CATALOG` dict in `scripts/catalog.py`.
3. Add a short blurb to this file.
4. Update `SKILL.md` "Catalog at a glance" if the new source fills a gap.

Source script pattern:

```python
#!/usr/bin/env python3
"""<Source name>: <one-line blurb>.

Docs: <URL>
Endpoint: <URL>
"""
import argparse, json, sys
# ... fetch and parse ...
def search(query: str, limit: int = 10) -> list[dict]:
    # ... return list of Document dicts ...
def main() -> int:
    p = argparse.ArgumentParser(...)
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)
    args = p.parse_args()
    docs = search(args.query, limit=args.limit)
    json.dump(docs, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0
if __name__ == "__main__":
    sys.exit(main())
```

## Sources intentionally NOT included

| Category | Why excluded |
|---|---|
| Walled (xiaohongshu, zhihu, wechat, discord) | Need a logged-in browser session. The deployer must bring their own account + CDP; bundling defaults would be unsafe. |
| `arxiv` PDFs / `crossref` PDF download | Out of scope; the model reads URLs via `web_fetch`. |
| Transcribe (ASR) | Needs `funasr` + `torch` (~2GB). Out of scope for this skill; recommend the upstream `omniseek` MCP server for ASR. |
| 100+ walled Chinese sources (一亩三分地, v2ex, juejin, ...) | Many are now reachable via the public proxies baked into upstream; future iterations can add keyless wrappers. |

If the user explicitly needs walled sources, point them at the upstream
MCP server (`omniseek[walled]` extra). This skill is the keyless,
zero-install, browser-free tier.