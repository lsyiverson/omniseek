# omniseek — multi-source retrieval skill for Mavis

A Mavis-compatible skill that distills [Battam1111/omniseek](https://github.com/Battam1111/omniseek)
(Apache-2.0) into a curated set of independent Python CLI scripts and a thin walled
tier for login-gated platforms (Zhihu, Xiaohongshu, Smzdm-read). Designed for
the **sweep → zoom → structure** research pattern: fan out across many sources,
score + dedupe, then drill into the top hits.

## What this skill does

| Domain | Sources | Notes |
|---|---|---|
| `papers` | arxiv, openalex, semantic_scholar, crossref, dblp, europe_pmc, zenodo | keyless, polite rate |
| `code` | github, hf_daily_papers | github needs optional `GITHUB_TOKEN` |
| `community` | hackernews, stackoverflow, reddit, bluesky | — |
| `news` | rss, smzdm, wayback | smzdm posts via RSS; details to car |
| `jobs` | mycareersfuture, remotive | — |
| `funding` | nsf_awards, nih_reporter | — |
| `walled` | zhihu (9222), xiaohongshu_search (9223), xiaohongshu_read (9223), smzdm_read (9226) | user-managed Chrome via CDP |

See `references/catalog.md` for the full inventory with endpoints, qualifiers, and rate
limits.

## Layout

```
omniseek-skill/
├── SKILL.md                  ← orchestrates the skill (loaded by Mavis)
├── README.md                 ← you are here
├── .gitignore
├── scripts/
│   ├── _cdp.py               ← shared Chrome DevTools Protocol helper (walled scripts)
│   ├── catalog.py            ← list every source, with --describe
│   ├── normalize_doc.py      ← merge / dedup / score across sources
│   ├── multi_search.py       ← fan-out wrapper for parallel source invocation
│   ├── launch_browser.sh     ← mac/linux launcher for walled Chrome profiles
│   ├── walled_health.py      ← probe all 4 CDP ports, report cookie state
│   ├── <one .py per source>  ← 20 free-tier scripts
│   └── walled/               ← login-gated scripts (use port above)
│       ├── zhihu.py
│       ├── xiaohongshu_search.py
│       ├── xiaohongshu_read.py
│       └── smzdm_read.py
└── references/
    ├── catalog.md            ← source inventory with details
    ├── normalize.md          ← Document envelope contract
    ├── patterns.md           ← sweep/zoom/structure workflow recipes
    ├── walled.md             ← walled tier trust model + port conventions
    └── sources-derived.md    ← upstream provenance + intentional omissions
```

## Quick start

**Install the skill** so Mavis can find it:

```bash
# Option A: direct copy
cp -r . ~/.minimax/skills/omniseek/

# Option B: symlink (lets you edit here and see changes live)
ln -sfn "$(pwd)" ~/.minimax/skills/omniseek

# Verify
node ~/.minimax/.builtin-skills/skill-creator/scripts/lint-skill.js \
    ~/.minimax/skills/omniseek
```

All 8 lint checks should pass (SKILL.md, frontmatter, kebab-case name, trigger hint,
no forbidden keys, line cap, no forbidden files, references resolve).

**Browse sources:**

```bash
python3 scripts/catalog.py                 # full inventory grouped by domain
python3 scripts/catalog.py --domain papers
python3 scripts/catalog.py --source smzdm --describe
```

**A typical sweep → zoom run:**

```bash
# Sweep
python3 scripts/multi_search.py "transformer attention" \
    --sources arxiv,openalex,semantic_scholar --limit 5 \
    > /tmp/sweep.json

# Zoom (merge + dedup + score)
python3 scripts/normalize_doc.py /tmp/sweep.json \
    --query "transformer attention" --keep-score \
    | head -80
```

**Walled tier — read for yourself first:**

```bash
# Launch a Chrome on the port your walled source expects.
# 9222  shared (zhihu)
# 9223  xiaohongshu (search + read)
# 9226  smzdm (read-only — no smzdm login needed, just a real browser fingerprint)
bash scripts/launch_browser.sh 9223 ~/.omniseek/chrome-9223 \
    https://www.xiaohongshu.com
#   ↑ log in by hand in the window that opens, then leave it running

# Verify
python3 scripts/walled_health.py

# Now drive it
python3 scripts/walled/xiaohongshu_search.py "字节跳动 面经" --limit 5
```

See `references/walled.md` for the full trust model, port map, and troubleshooting table.

## Document envelope contract

Every script returns a JSON array of Documents. Each Document has:

```python
{
    "source": "arxiv",                  # stable id; also used by _SOURCE_PRIORITY in normalize_doc
    "source_id": "https://arxiv.org/abs/2301.0001",
    "title": "...",
    "url": "https://arxiv.org/abs/2301.0001",
    "content": "snippet or full body",
    "authors": ["..."],
    "published_at": "2026-09-21T01:06:20Z",  # ISO-8601 UTC, or None
    "fetched_at": "2026-09-21T01:19:40Z",    # always set, ISO-8601 UTC
    "metadata": {
        # free-form per source; see references/normalize.md for shapes
    }
}
```

Scripts print the array on stdout and `[source].http_error` (or similar) on
stderr. Empty result + exit code 0 is **not** an error — that's the contract.

## Adding a new source

The standard pattern is:

1. Pick the public endpoint and decide the kind (free / walled).
2. For free sources: a new file `scripts/<name>.py` that:
   - takes a query positional + `--limit` (matching `multi_search.py`'s fan-out)
   - parses the response into Documents with the envelope above
   - prints a JSON array
3. For walled sources: same shape, but pulls the page through CDP via `_cdp.py`.
4. Add the entry to `scripts/catalog.py` `CATALOG` dict.
5. Add a row to `references/catalog.md`.
6. Run `python3 scripts/lint-skill.js` and the catalog discovery.

See `references/patterns.md` for the broader sweep/zoom/structure recipes.

## Development

Lint:

```bash
node ~/.minimax/.builtin-skills/skill-creator/scripts/lint-skill.js .
```

Smoke test one free-tier source:

```bash
python3 scripts/arxiv.py "transformer attention" --limit 3 | python3 -m json.tool
```

Smoke test walled (requires a running Chrome on the right port):

```bash
python3 scripts/walled_health.py    # confirm the port is alive
python3 scripts/walled/xiaohongshu_search.py "phd" --limit 3 | python3 -m json.tool
```

## Provenance

Distilled from [`Battam1111/omniseek`](https://github.com/Battam1111/omniseek)
(Apache-2.0). Each `scripts/*.py` corresponds to one source module in the upstream
repo; `references/sources-derived.md` records the exact mapping so any port or fix
is traceable.

**Upstream has 218+ sources across 32 domains. This skill ships 20 free data
sources + 4 walled readers + 3 orchestrators.** The walled tier follows the
upstream "user-managed Chrome via CDP" pattern — we never see your password,
the script closes only the tab it opens.

## License

Apache-2.0, inherited from the upstream project. See the upstream LICENSE for
the full text.