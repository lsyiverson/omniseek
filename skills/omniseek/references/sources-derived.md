# Source Provenance — how each script maps back to upstream `omniseek`

This skill distills 24 source adapters from the upstream
[`Battam1111/omniseek`](https://github.com/Battam1111/omniseek) (Apache-2.0).
Each script in `scripts/` corresponds to one source module in the upstream
repo. The mapping below records the upstream file each script is derived
from, so anyone porting a fix or new feature knows where to look.

## Source file → script mapping

| This skill's script | Upstream module | Domain | Notes |
|---|---|---|---|
| `scripts/arxiv.py` | `src/omniseek/core/sources/api/arxiv_source.py` | papers | Same Atom endpoint, same `au:` / `cat:` / `ti:` syntax, same 1-req/3s gate |
| `scripts/openalex.py` | `src/omniseek/core/sources/api/openalex_source.py` | papers | Same inline filter allowlist; same polite-pool `mailto:` behavior |
| `scripts/semantic_scholar.py` | `src/omniseek/core/sources/api/semantic_scholar_source.py` | papers | Same qualifier parsing (`year:`, `venue:`, `min_citations:`); same S2_API_KEY path |
| `scripts/crossref.py` | `src/omniseek/core/sources/api/crossref_source.py` | papers | Same `/works` endpoint + by-DOI mode |
| `scripts/dblp.py` | `src/omniseek/core/sources/api/dblp_source.py` | papers | Adds `--author` mode (upstream's `dblp_author_source.py`) |
| `scripts/europe_pmc.py` | `src/omniseek/core/sources/api/europepmc_source.py` | papers | Keyless full-text spine upstream calls out |
| `scripts/zenodo.py` | `src/omniseek/core/sources/api/zenodo_source.py` | papers | Same `/api/records` endpoint |
| `scripts/github.py` | `src/omniseek/core/sources/api/github_source.py` + `github_trending_source.py` | code | Combines platform surfaces (code/issues/PR/discussions/repo activity/tree); same `org:`/`tree:` routing |
| `scripts/hf_daily_papers.py` | `src/omniseek/core/sources/api/hf_daily_papers_source.py` | code | Same endpoint; same date fallback |
| `scripts/hackernews.py` | `src/omniseek/core/sources/api/hackernews_source.py` | community | Same stories+comments 50/50 budget split; same Algolia endpoint |
| `scripts/stackoverflow.py` | `src/omniseek/core/sources/api/stackoverflow_source.py` (via `_stackexchange.py`) | community | Same SE API; same question+top-answers merge |
| `scripts/reddit.py` | `src/omniseek/core/sources/api/reddit_source.py` | community | Arctic Shift mirror; same fallback for Reddit WAF blocks |
| `scripts/bluesky.py` | `src/omniseek/core/sources/api/bluesky_source.py` | community | Same public AT Protocol endpoint |
| `scripts/rss.py` | `src/omniseek/core/sources/scrape/_rss.py` | news | Generic aggregator pattern from upstream |
| `scripts/smzdm.py` | (no upstream equivalent) | news | Built fresh — upstream omits 什么值得买. Uses the public `post.smzdm.com/feed` RSS (no auth, no fingerprint challenge) |
| `scripts/wayback.py` | `src/omniseek/core/sources/api/wayback_source.py` | news | Same CDX query |
| `scripts/mycareersfuture.py` | `src/omniseek/core/sources/api/mycareersfuture_source.py` | jobs | Same endpoint |
| `scripts/remotive.py` | `src/omniseek/core/sources/api/remotive_source.py` | jobs | Same endpoint |
| `scripts/nsf_awards.py` | `src/omniseek/core/sources/api/_bulk_funding.py` (NSF path) | funding | Same endpoint |
| `scripts/nih_reporter.py` | `src/omniseek/core/sources/api/_bulk_funding.py` (NIH path) | funding | POST API; same advanced_text_search |
| `scripts/catalog.py` | `scripts/gen_sources_doc.py` (upstream) + `docs/sources.md` | (orchestrator) | Static catalog distilled to Python dict |
| `scripts/normalize_doc.py` | `src/omniseek/core/normalize.py` (upstream) | (orchestrator) | Same `Document` envelope + dedup-by-URL pattern |
| `scripts/multi_search.py` | (no upstream equivalent) | (orchestrator) | New — replaces the upstream MCP server fan-out with a shell fan-out |

## Upstream sources NOT yet distilled

The upstream ships 218+ sources across 32 domains. This skill ships 20
keyless data sources plus 4 walled readers (last delta: `xiaohongshu_read`,
the note-detail body + comment extractor that pairs with the existing
`xiaohongshu_search`). The major categories NOT yet
covered:

| Category | Reason | Future plan |
|---|---|---|
| 40+ organization paper feeds (DeepSeek, OpenAI, Meta FAIR, …) | Most route through OpenAlex with raw-affiliation filters — a small but tedious port | See `references/patterns.md` "Adding a new source" |
| CORDIS / UKRI / NSERC / NSFC / CIHR / SSHRC | International funding mirrors the NSF/NIH pattern | Bundle as a `_bulk_funding.py` analogue |
| ircc_ee_rounds / IRCC processing times | Specific to Canadian immigration | Add as `ircc_*.py` |
| RSS bundles (academic_ai_labs, frontier_labs, …) | Bundle is just a list of feeds; trivial to construct on top of `rss.py` | Build a `feeds.example.txt` |
| GitHub releases / HuggingFace hub | Different API surface (releases.atom, hub listing) | Trivial port |
| Stack Exchange sister sites (crossvalidated, ai_se, academia_se, datascience_se, cs_se) | All use the same SE API with a different `site=` value | Parameterize `stackoverflow.py` |
| HackerNews × Disqus-Forum-Discourse general forum scraper | Generic JS-rendered scrape | Out of scope without Playwright |
| 14 walled (login) sources | Requires a CDP browser session | NEVER bundled in this skill |

The intent is to grow this skill opportunistically as users hit sources not
yet covered. Each addition is ~50–150 lines and follows the `Document`
envelope from `references/normalize.md`.

## License

This skill is distributed under the same license as the upstream:
**Apache-2.0**. See `LICENSE` (intentionally not auto-generated; refer to
upstream).

The upstream NOTICE file credits the original authors of each data source
(Semantic Scholar team, OpenAlex team, Crossref, arXiv, etc.). When you
cite a result, cite BOTH this skill's source AND the upstream data
provider.