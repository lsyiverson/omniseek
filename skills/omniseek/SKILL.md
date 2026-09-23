---
name: omniseek
description: |
  Multi-source deep retrieval across papers, code, community Q&A, news, jobs, and
  funding feeds. Use this skill when the user wants breadth AND structure that
  plain web search can't give — find a paper across arxiv/OpenAlex/Semantic
  Scholar, search GitHub issues + code, pull HackerNews/Reddit/StackOverflow
  threads, search Chinese community forums (NGA 玩家社区, 知乎, 小红书), fetch
  job boards, query NSF/NIH grants, or aggregate RSS/blog feeds.
  Triggers on phrases like "find papers on", "search code for", "HackerNews
  discussion of", "grant awards for", "GitHub issues about", "Stack Overflow
  for", "RSS feed of", "arxiv", "openalex", "semantic scholar", "NGA 论坛",
  "nga 攻略/评测/讨论". Do NOT use it for single web-page reading (use browser
  or web_fetch), local file search, or pure LLM reasoning — this skill is a
  DATA RETRIEVAL layer, not a research agent. The model still does the
  synthesis; this skill only fetches.
---

# OmniSeek

Multi-source retrieval toolbox distilled from `Battam1111/omniseek`. Same
catalog-first design: every source ships as a standalone CLI script that takes
a query and prints a normalized JSON document list to stdout. The agent
orchestrates by calling scripts and consuming their JSON — no MCP server, no
container, no state.

## Inputs to collect

- **Query string** — what the user wants to find (mandatory; can be empty for
  catalog browse)
- **Source set** — which data sources to fan out across. Default is
  `papers,code,community,news`. Override per task. See
  `references/catalog.md` for the full inventory.
- **Limit** — per-source cap (default 10, max 50)
- **Optional filters** — date range, language, venue, region (each source
  accepts its own qualifiers — see each script's `--help`)

If the user did not specify a source, infer from intent:

| Intent keywords | Default sources |
|---|---|
| paper, preprint, citation, abstract, arxiv | `arxiv openalex semantic_scholar crossref` |
| code, repository, github, issues, PR | `github` |
| discussion, thread, opinion, community | `hackernews reddit stackoverflow bluesky` |
| job, salary, hiring, position | `mycareersfuture remotive layoffs_tracker` |
| grant, funding, award, NIH, NSF | `nsf_awards nih_reporter cordis_eu` |
| news, blog, RSS, announcement | `rss` |
| 中文消费, 数码评测, 购物攻略, smzdm, 值得买 | `smzdm` |
| 中文论坛, NGA, ngabbs, 玩家社区, 游戏/二次元/数码讨论, 攻略, 装机 | `nga` (walled — port 9222, needs NGA login) |
| historical, deleted, wayback | `wayback` |

## Procedure

### 1. Route — pick sources

Pick 1–5 sources per call. More than 5 fans out the budget without raising
recall. When in doubt, start with `arxiv + openalex + semantic_scholar` (the
paper triangle covers ~95% of academic queries).

### 2. Fan out — invoke scripts in parallel

Call each source script via `bash`. Scripts are independent and stateless; run
them in a single message with multiple `bash` tool calls. Each script takes
the query, a `--limit`, and source-specific flags. Output is a JSON array on
stdout.

```bash
# `<skill-dir>` is wherever this skill is installed for your agent runtime
# (e.g. ~/.claude/skills/, ~/.codex/skills/, or the equivalent for your agent).
python3 <skill-dir>/omniseek/scripts/arxiv.py "transformer attention" --limit 5
python3 <skill-dir>/omniseek/scripts/openalex.py "transformer attention" --limit 5
python3 <skill-dir>/omniseek/scripts/semantic_scholar.py "transformer attention" --limit 5
```

### 3. Normalize — collapse to Document shape

Every script returns JSON conforming to the same `Document` envelope (see
`references/normalize.md`). Use `scripts/normalize_doc.py` to merge results
from multiple sources, dedup by URL + title fingerprint, and sort by a simple
recency × query-match score.

### 4. Judge — pick the next wave

Read the merged results. Three signals tell you whether to keep going:

- **Coverage gap** — every result is from one source, or the top hits don't
  answer the question. → Fire a second wave with a different source set
  (e.g. add `europepmc` for biomedical, add `crossref` for formal publications)
- **Identity gap** — the question is about a person / lab / paper. → Drop
  into specific tools: `github.py org:<name>`, `dblp.py author:<name>`,
  `semantic_scholar.py paper:<DOI>`
- **Depth gap** — you have a hit list but need the actual content. → Fetch
  the canonical URL via `web_fetch` (browser for JS-walled pages) and read
  the full text. **Known anti-scraping exception: smzdm.com /
  post.smzdm.com.** `web_fetch`/plain HTTP gets served a Tencent captcha
  interstitial on essentially every request (fingerprint probe, not a login
  wall). Don't bother retrying `web_fetch` for smzdm URLs — go straight to
  a real browser: `scripts/walled/smzdm_read.py <url>` (CDP, port 9226) or
  drive a local browser tool directly. **No smzdm account/login is
  required** — a real Chrome fingerprint alone passes the probe.
  **Known login-walled exception: bbs.nga.cn (NGA玩家社区).** NGA has no
  public API: search (`thread.php?key=`) and most board reads (`read.php?tid=`)
  require a logged-in account, and the site throttles search hard. Don't
  `web_fetch` NGA — route both steps through the shared logged-in Chrome on
  port 9222: `scripts/walled/nga.py "<关键词>"` for the hit list, then
  `scripts/walled/nga.py --read <tid>` for the thread body (search returns
  tids, so the two compose).

### 5. Cite — never lose provenance

Every Document carries `source`, `source_id`, `url`, `fetched_at`. When
synthesizing for the user, always name the source. The user's job is to judge
trust — your job is to surface it cleanly.

## Output contract

Every source script returns a JSON array of `Document` objects on stdout. On
error it prints `[]` and a structured note on stderr (exit 0). On hard
failure (e.g. no internet, DNS fail) it exits non-zero with the exception on
stderr — the caller can then choose to retry, skip, or surface to the user.

`Document` envelope (canonical fields; sources add their own `metadata`):

```json
{
  "source": "arxiv",
  "source_id": "2406.01234",
  "title": "...",
  "url": "https://arxiv.org/abs/2406.01234",
  "content": "abstract text or summary",
  "authors": ["Last, F.", "..."],
  "published_at": "2024-06-01T00:00:00Z",
  "fetched_at": "2026-09-20T12:34:56Z",
  "metadata": { ... source-specific ... }
}
```

`metadata` is a free-form dict carrying whatever the source naturally
exposes (citation counts, comment counts, awards, stars, etc.). See each
script's docstring for the shape.

## Failure handling

- **Empty result `[]`** — the source legitimately had nothing. Don't retry;
  move to a different source.
- **Stderr note with `circuit_breaker_open` / `rate_limited`** — the source
  is temporarily unavailable. Back off and try a different source; don't
  hammer the failing one.
- **Network error / DNS fail** — exit code != 0. Skip this source, log it,
  tell the user "X sources skipped due to network error".
- **Quota exceeded (HTTP 429 with API key)** — stop using that key, switch
  to a keyless mirror if one exists (see `references/catalog.md`).
- **Malformed upstream response** — the script prints `[]` and a `parse_error`
  note. The next run after the upstream fixes itself will recover; no retry
  needed.
- **Anti-scraping captcha (e.g. smzdm.com pages)** — if `web_fetch` /
  plain HTTP returns a Tencent-captcha interstitial (`TCaptcha`,
  `captcha.show`) instead of content, don't retry `web_fetch`. Skip
  straight to a real browser: `scripts/walled/smzdm_read.py <url>` (CDP
  port 9226) or a local browser tool. This is a fingerprint probe, not an
  auth wall — no login/account is needed to read the page.
- **Walled / login-gated source (NGA, 知乎, 小红书)** — the script exits 0
  with `[]` plus a stderr note like `login_required` or
  `search_rate_limited`. Tell the user which Chrome port is involved and
  what to do (`scripts/launch_browser.sh <port>`, then log in by hand);
  don't fall back to blind `web_fetch` retries, and don't hammer the search.

## Examples

### Find a paper

```bash
python3 scripts/arxiv.py "speculative decoding llm" --limit 5 --year 2024
python3 scripts/semantic_scholar.py "speculative decoding llm" --limit 5 --year 2024
python3 scripts/normalize_doc.py --merge *.json | head -20
```

Output: a merged list of papers with deduplication by DOI/arXiv ID. Use
metadata.citationCount from S2 to gauge influence, metadata.year from arXiv
to gauge freshness.

### Find a GitHub org's newest repos

```bash
python3 scripts/github.py "org:openai" --limit 20
```

Output: newest repos with stars, description, primary language, last-pushed
timestamp.

### Track a grant topic

```bash
python3 scripts/nsf_awards.py "alignment interpretability" --limit 20
python3 scripts/nih_reporter.py "LLM clinical NLP" --limit 20
```

Output: structured grant records with PI, institution, amount, abstract,
start date. Use these to identify who is funding the work, not just who's
publishing it.

### Search a Chinese forum (NGA — walled)

```bash
scripts/launch_browser.sh 9222 https://bbs.nga.cn   # once; log in by hand
python3 scripts/walled/nga.py "黑神话 帧数 优化" --limit 5
python3 scripts/walled/nga.py --read 44321111 --max-posts 20
```

Output: search hits carry tid / title / board / author / reply count — those
are titles only, so read the ones that matter. Read mode returns the thread
body in `content` plus `metadata.posts` (one entry per floor with author,
time, uid). NGA throttles search per account: keep `--limit` small and don't
loop the search.

### Read a 小红书 note AND see its photos (walled)

```bash
scripts/launch_browser.sh 9223 ~/.omniseek/chrome-9223 https://www.xiaohongshu.com  # once
python3 scripts/walled/xiaohongshu_search.py "露营装备" --limit 5
URL=$(python3 scripts/walled/xiaohongshu_search.py "露营装备" --limit 1 \
      | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['url'])")
python3 scripts/walled/xiaohongshu_read.py "$URL" --max-comments 20 > /tmp/note.json
python3 scripts/walled/xiaohongshu_view.py --note-url "$URL" --out-dir /tmp/xhs_imgs
```

Output: `xiaohongshu_read` gives you the note text/comments AND
`metadata.images` (the note's own CDN photo URLs). Many 图文笔记 carry their
real information in the pictures, not the caption — `xiaohongshu_view`
downloads those URLs (with the `Referer` header the CDN requires) into
`/tmp/xhs_imgs/*.jpg`; read those files with a file-viewing tool to actually
see them. `xiaohongshu_view` also accepts raw URLs directly (`--file` or
positional args) if you already have `metadata.images` from a saved run.

### Browse a source's full catalog

```bash
python3 scripts/catalog.py --domain papers
python3 scripts/catalog.py --source arxiv --describe
```

Output: catalog index. Use `--describe` to print the source's full
description + supported qualifiers.

## Catalog at a glance

| Domain | Keyless sources | Walled sources (bring your own login) |
|---|---|---|
| papers | arxiv, openalex, semantic_scholar, crossref, dblp, europe_pmc, zenodo | — |
| code | github, hf_daily_papers | — |
| community | hackernews, stackoverflow, reddit, bluesky | zhihu (port 9222), nga (port 9222, search + read), xiaohongshu (port 9223, search + read + image view) |
| news | rss (generic aggregator), smzdm (中文消费原创 RSS), wayback | — |
| jobs | mycareersfuture, remotive, layoffs_tracker | — |
| funding | nsf_awards, nih_reporter, cordis_eu, ukri_gtr | — |

The walled tier is **opt-in and off-by-default**. Each walled source drives a
real Chrome you launched, with your own logged-in session, via the Chrome
DevTools Protocol on a per-platform port. We never see your password. See
`references/walled.md` for setup, port mapping, and the trust model.

Quickest walled run (NGA — search then read):

```bash
scripts/launch_browser.sh 9222 https://bbs.nga.cn   # log in by hand once
python3 scripts/walled/nga.py "黑神话 帧数 优化" --limit 5
python3 scripts/walled/nga.py --read 44321111 --max-posts 20
```

See `references/catalog.md` for the full inventory with description, tier
(`free` / `walled`), and route qualifiers for every source.

## Reference

- `references/catalog.md` — full source catalog (description, tier, qualifiers, rate limits)
- `references/normalize.md` — Document envelope spec, dedup rules, sort scoring
- `references/patterns.md` — orchestration patterns (sweep/zoom/structure, identity resolution, field skeleton)
- `references/sources-derived.md` — which omniseek module each script distills from, with commit hash

## Windows (win32) platform notes

This skill assumes a POSIX shell (bash / zsh) and `python3` on the system
PATH. It is written and tested on macOS / Linux.

For Windows users, the recommended paths are:

1. **WSL (Windows Subsystem for Linux)** — install Ubuntu from the
   Microsoft Store, then run the skill from inside the WSL terminal. All
   `python3` + `bash` examples work unchanged.
2. **Git Bash** — bundled with Git for Windows. POSIX-ish but some
   default tools (`jq`, `curl`, `find`) may be missing or different
   versions. Install Python for Windows and call it as `python` instead
   of `python3`.
3. **Docker** — the upstream `omniseek` MCP server has a `Dockerfile` /
   `docker-compose.yml`. If you need a single binary instead of 22
   scripts, run that. This skill is the script-first variant.

In PowerShell, `python3` is usually just `python`. The scripts'
`subprocess` calls inside `multi_search.py` already use `sys.executable`,
so they resolve whichever interpreter is invoking them.
