# Document Envelope — the shared contract

Every source script in this skill returns a JSON array of `Document` objects
on stdout. The envelope is the contract that lets `normalize_doc.py` and
`multi_search.py` mix results across sources without per-source code.

## Canonical fields

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

| Field | Type | Required | Notes |
|---|---|---|---|
| `source` | str | yes | Short source name (matches `scripts/catalog.py`) |
| `source_id` | str | yes | The source's own canonical ID (DOI, arXiv ID, HN objectID, etc.) |
| `title` | str | yes | Display title (single line; no markdown) |
| `url` | str | yes | Canonical URL (HTTPS preferred). Used for dedup fingerprint. |
| `content` | str | no | Abstract / body / selftext. May be empty. |
| `authors` | list[str] | no | Author display names. May be empty. |
| `published_at` | str | no | ISO 8601 in UTC (`...T00:00:00Z`). Used for recency scoring. |
| `fetched_at` | str | yes | Always set by the script — `datetime.now(timezone.utc).isoformat()` |
| `metadata` | dict | yes | Free-form. See per-source schema below. |

`metadata` is a free bag. Each source puts its own signal there:
citation counts, comment counts, stars, salary, grant amount, etc. Scripts
must NOT invent fields; they should only carry what the upstream source
naturally provides.

## Per-source metadata shape

Every script documents its own `metadata` keys in its docstring. The most
common shapes:

### papers (arxiv / openalex / semantic_scholar / crossref / dblp / europe_pmc / zenodo)

```json
{
  "doi": "10.1234/abcd",
  "venue": "NeurIPS",
  "year": 2024,
  "type": "article",
  "citation_count": 42,
  "is_oa": true,
  "oa_url": "https://...",
  "language": "en"
}
```

### code (github_repo / github_issue / github_code / github_tree)

```json
{
  "kind": "repo",
  "full_name": "owner/repo",
  "stars": 12345,
  "language": "Python",
  "topics": ["llm", "agent"],
  "last_pushed_at": "2026-09-01T00:00:00Z"
}
```

### community (hackernews_*, stackoverflow_*, reddit, bluesky)

```json
{
  "kind": "story" | "comment" | "question" | "answer" | "post",
  "points": 250,
  "num_comments": 84,
  "tags": ["rust", "async"],
  "subreddit": "MachineLearning"
}
```

### jobs (mycareersfuture / remotive)

```json
{
  "company": "...",
  "uen": "...",             // mycareersfuture only
  "salary_min": 8000,
  "salary_max": 14000,
  "salary_currency": "SGD",
  "salary_type": "Monthly",
  "location": "Singapore"
}
```

### funding (nsf_awards / nih_reporter)

```json
{
  "award_id": "...",
  "pi_last_name": "...",
  "awardee_name": "...",
  "amount": 500000,
  "currency": "USD",
  "fund_program_name": "...",
  "directorate": "...",
  "fiscal_year": 2025
}
```

## Dedup

`scripts/normalize_doc.py --dedup` collapses duplicates across sources.
Two Documents are "the same" if their `url` (or, if URL is empty, their
title-alnum-lowercase) matches after SHA1.

Deduplication keeps the FIRST occurrence in iteration order. To control
priority, run sources in your preferred order before merging — e.g. run
`arxiv` first if you trust its canonical IDs most.

## Scoring

`--sort` (default on) computes a `_score` for each document using three
ingredients:

- 40% — recency (clamped 0..1 over a 5-year window; "no date" = 0)
- 40% — query match (fraction of query terms found in title+content)
- 20% — source priority (a per-source constant in `normalize_doc.py`)

Tweak `_SOURCE_PRIORITY` in `normalize_doc.py` if your domain weights
differ (e.g. for a clinician, `europe_pmc` > `arxiv`).

## Error handling contract

Each script follows the same rule:

- **HTTP 4xx/5xx** → print `[source].http_error: ...` to stderr; print `[]`
  on stdout; exit 0. Caller treats `[]` as "no results", not as an error.
- **HTTP 429 (rate-limited)** → same as above; consider backing off.
- **JSON parse error** → print `[source].parse_error: ...` to stderr;
  print `[]` on stdout; exit 0.
- **Hard network / DNS failure** → print to stderr; exit non-zero. Caller
  may choose to skip the source.

This makes a multi-source fan-out robust: one broken source doesn't kill
the others.

## Examples

### Merge + dedup + sort

```bash
python3 scripts/arxiv.py "transformer attention" --limit 5 > /tmp/a.json
python3 scripts/openalex.py "transformer attention" --limit 5 > /tmp/o.json
python3 scripts/semantic_scholar.py "transformer attention" --limit 5 > /tmp/s.json
python3 scripts/normalize_doc.py /tmp/a.json /tmp/o.json /tmp/s.json \
    --query "transformer attention" --keep-score
```

### Filter to last year

```bash
python3 scripts/normalize_doc.py results.json --max-age-days 365 --query "..."
```

### Drop a noisy source

```bash
python3 scripts/normalize_doc.py results.json --filter-source bluesky --filter-source reddit
```