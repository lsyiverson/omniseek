# Orchestration Patterns — how an agent should use these scripts

This skill is a retrieval LAYER. The agent does the synthesis; the scripts
do the fetching. The patterns below are the orchestration shapes the agent
should reach for.

## The 3-turn rhythm: sweep, zoom, structure

Adopted from the upstream `omniseek-investigate` skill. Every deep
investigation follows the same beat.

### WAVE 1 — sweep

Fire several independent source scripts in parallel. One round-trip, all
results at once.

```bash
python3 scripts/arxiv.py "speculative decoding" --limit 5 &
python3 scripts/openalex.py "speculative decoding" --limit 5 &
python3 scripts/semantic_scholar.py "speculative decoding" --limit 5 &
wait
```

Or use the bundled fan-out script:

```bash
python3 scripts/multi_search.py "speculative decoding" \
    --sources arxiv,openalex,semantic_scholar --limit 5
```

### Judge

Read the wave-1 results. Three signals tell you what to do next:

| Signal | What it means | Next move |
|---|---|---|
| All results from one source | Coverage gap | Add another source: `dblp` for older CS, `europe_pmc` for biomedical, `crossref` for formal venues |
| Question is about a person | Identity gap | Use identity-bearing sources: `dblp.py --author`, `github.py "user:NAME"`, `semantic_scholar.py` with the PI's name in `query` |
| Question is about funding/money | Funding gap | Add `nsf_awards.py`, `nih_reporter.py` |
| Question is about jobs | Jobs gap | Add `mycareersfuture.py`, `remotive.py` |
| Top hits don't answer the question | Query gap | Rephrase; try synonyms; try an institution name instead of a topic |

### WAVE 2 — zoom

Fire follow-up scripts informed by wave-1 signals. Re-run `multi_search.py`
with a different `--sources` list, or pick a single source to drill.

```bash
# zoom: a specific author
python3 scripts/dblp.py --author "Yoshua Bengio" --limit 20

# zoom: a specific lab's GitHub activity
python3 scripts/github.py "org:openai" --limit 20
```

### Structure

Build the answer from the merged documents. Every Document carries
provenance (`source`, `url`, `fetched_at`). When you cite a fact, name the
source. When sources disagree, surface both — don't pick a winner.

## Pattern: identity resolution

For "who is X" or "what does X work on":

1. `dblp.py --author "X Last"` → canonical CS publication list + DBLP ID
2. `semantic_scholar.py --lookup "<DOI or arXiv ID>"` → single paper
   enrichment (citation count, TLDR)
3. `github.py "user:X"` or `github.py "org:X"` → code/issue footprint
4. Cross-reference: `normalize_doc.py --dedup` collapses papers that appear
   under different author name forms.

## Pattern: paper deep-dive

For "tell me about this paper" given a URL or DOI:

1. Identify the canonical ID (`arxiv.py`, `crossref.py --doi`, `dblp.py`)
2. Pull metadata + abstract from that source
3. If you need the full text:
   - OA: `crossref.py` returns the OA URL in `metadata.oa_url`
   - PMC: `europe_pmc.py` returns the pmcid; the full body is reachable
     via the `fullTextXML` endpoint (a future enhancement)
   - Otherwise: `web_fetch` the arxiv PDF or publisher page

## Pattern: field / topic mapping

For "what's the state of X":

1. Sweep with `multi_search.py --sources arxiv,openalex,semantic_scholar`
2. For the top 5-10 hits, run `semantic_scholar.py` with no extra query
   but pull their citation counts — that's your influence signal
3. For each hit, follow its citation graph via Semantic Scholar's API
   (a future enhancement)
4. `normalize_doc.py --query "..." --sort` produces the final ranked list

## Pattern: lab / research group evaluation

For "should I join X's lab?":

1. `github.py "org:X"` → repo footprint + activity
2. `dblp.py --author "PI Last"` → publication count + venues
3. `nsf_awards.py "..." --pi "PI Last"` → active grants + amount
4. `hackernews.py "X"` → HN mindshare
5. `bluesky.py "PI Last"` → recent public posts (a candid signal)
6. Merge via `normalize_doc.py` and synthesize

## Pattern: regulatory / policy tracking

For "what's the latest rule for X":

1. Identify the authoritative source's RSS or updates URL
2. `rss.py <URL>` (one or more feeds) → recent items
3. `wayback.py <URL>` → history of changes to the canonical page
4. Optionally `reddit.py --subreddit <relevant>` for community reaction
5. Synthesize with a "what changed + when + what the community says" frame

## Pattern: job market snapshot

For "is X role hot in Y region?":

1. `mycareersfuture.py "..."` (SG) and/or `remotive.py "..."` (global remote)
2. Filter / sort via `normalize_doc.py --sort --query "..."`
3. Cross-reference: `hackernews.py "..."` for salary mentions / "Who's
   hiring" threads

## Pattern: failed-source recovery

When a source returns `[]`:

1. Read stderr: `[source].http_error` → network. Try a different source.
2. `[source].parse_error` → upstream changed shape. Skip; file a bug.
3. Empty (no stderr note) → legitimate miss. The source genuinely had
   nothing; move on.

When a source returns 429 / rate-limit note:

1. Stop using that source for the rest of this session.
2. Switch to a keyless mirror: arxiv ↔ openalex; s2 ↔ crossref/dblp;
   stackoverflow ↔ reddit (same topics, different crowd).
3. Consider adding `OMNISEEK_CONTACT_EMAIL` (or the relevant API key env
   var) for a faster lane on the next call.

## Pattern: budget discipline

- Surface (fast): 1 wave, 2-3 sources, `--limit 5`
- Standard: 2 waves (sweep + zoom)
- Deep: 2-3 waves + full-text fetch via `web_fetch`
- Cap total source calls at ~15 per session to avoid hitting per-IP
  rate limits (especially on Stack Exchange and Remotive)

If you hit a wall, drop a source rather than spam it. Better to have a
high-quality 8-document set than a noisy 80-document set.

## Anti-patterns

❌ **Calling `multi_search.py` with all 19 sources**. Spreads budget thin
and most results are off-topic.

❌ **Treating `[]` as a source failure**. `[]` means "no results"; only
non-zero exit or stderr `*_error` means failure.

❌ **Re-running a 429 source with exponential delays**. The first call's
note says you're being throttled; backing off does not un-throttle you
faster on most public APIs. Wait at least a few minutes or move on.

❌ **Re-parsing script output**. Scripts already emit the canonical
`Document` JSON. Pipe through `normalize_doc.py`, don't re-implement.

❌ **Storing fetched_at**. It's per-fetch. Use it for staleness checks
inside the session; don't persist it across sessions.

❌ **Filtering by `_score` blindly**. The score is recency + query-match +
source priority. If you want pure citation-count ranking, look at
`metadata.citation_count` from S2 and sort on that.