# Verify References — Reference

## Progress output

During `verify`, each reference is logged as it is resolved:

```
Verifying references in 2 report(s) (48 reference(s) total)...

  Report 1/2: work/deep/research_init.md (36 reference(s))
    [1/36] [1] Attention Is All You Need -> verified (singleton)
    [2/36] [2] BERT: Pre-training of Deep Bidirectional… -> verified (cached)
    [3/36] [3] Some Obscure Paper Title -> ambiguous
    ...
    refs=36 verified=29 ambiguous=3 not_found=2 errored=2 -> research_init.json

  Report 2/2: work/deep/research_deep.md (12 reference(s))
    [1/12] [1] ...
```

During `retry`, only unresolved records are retried:

```
Retrying unresolved references in 1 sidecar(s) (5 to retry)...

  research_init.json (5 to retry)
    [1/5] [12] Paper That Failed Earlier -> recovered (title_search)
    [2/5] [15] Another Failed Paper -> not_found
  research_init.json: retried=5 recovered=2 verified=31/36
```

Status labels: `verified (singleton|title_search|cached)`, `ambiguous`, `not_found`, `rate_limited`, `budget_exceeded`, `network_error`, `bad_request`, `skipped`, `recovered (...)`.

## Identifier resolution

| URL shape | Identifier | Lookup |
|---|---|---|
| `doi.org/10.x/…`, bioRxiv / medRxiv / chemRxiv | `doi` | `/works/doi:…` |
| `arxiv.org/abs|pdf/…` (new or legacy ID, any `vN`) | `arxiv` | `/works/doi:10.48550/arXiv.<id>` |
| `pubmed.ncbi.nlm.nih.gov/<digits>` | `pmid` | `/works/pmid:…` |
| `…/PMC<digits>` | `pmcid` | none — straight to title search |
| anything else | – | title search |

arXiv IDs go through their DataCite DOI because `/works/https://arxiv.org/abs/<id>` always 404s. PMCIDs get no singleton call at all: OpenAlex indexes no `pmcid` for the PMC records these reports cite (`/works/pmcid:…` and `filter=ids.pmcid:…` both come back empty), so the request would only cost a round trip before the title-search fallback. Revisit if OpenAlex adds coverage.

Titles are cleaned before searching — `[2512.04123]` / `(PDF)` prefixes, ` - PubMed` suffixes, and `Journal | Free Full-Text | … | HTML` chrome are dropped. Commas, pipes, and `?`/`*` wildcards are removed because OpenAlex rejects them inside a `title.search` value (HTTP 400). Similarity is always scored against the original title.

## De-duplication & caching

1. **Dedup key** (priority): DOI → arXiv (as its DOI) → PMID → PMCID → normalized title
2. **In-run memo**: one OpenAlex lookup per distinct work across all files in a run
3. **Persistent cache**: `openalex_cache.json` per report directory (`--cache auto`), or one shared file when `--cache PATH` is given

The cache stores **verified records only**. Caching a miss would make `retry` a no-op, since every unresolved record would return as a cache hit. Legacy flat caches are read, stripped of negatives, and rewritten as `{"version": 2, "entries": {…}}`. Writes are atomic and flushed every 25 live calls, so an interrupted run keeps what it resolved.

End-of-run summary reports `live_calls`, `cache_hits`, and `memo_hits`.

## OpenAlex cost model

`[openalex] api_key` in `.env` (or `OPENALEX_API_KEY`) is **optional** — it raises the daily cap. Free key: [openalex.org/settings/api](https://openalex.org/settings/api). Without one, set `OPENALEX_MAILTO` (or `[openalex] mailto`) to use the polite pool; with neither, requests go to the more aggressively throttled anonymous pool.

| Lookup type | Approx. cost | Notes |
|---|---|---|
| Singleton (DOI / arXiv / PMID) | $0 | Free, unlimited |
| Title filter (`filter=title.search:`) | $0.0001/call | Prefer over full `search=` |
| Full-text search | $0.001/call | Avoid unless necessary |

Free tier: ~$1/day with an API key. Use `--max-cost` and `--rate 5`.

## Error taxonomy

| Code | Meaning | Halts run | Retry helps |
|---|---|---|---|
| `ambiguous` | Best title match below `--sim-threshold` | no | with `--sim-threshold` / `--force-search` |
| `not_found` | OpenAlex has no such work | no | rarely (blogs and vendor pages are not indexed) |
| `network_error` | Transport failure or 5xx after retries | no | yes |
| `bad_request` | 4xx other than 429 — the request itself was rejected | no | only after the query is fixed |
| `rate_limited` | 429 after retries | yes | yes, later |
| `budget_exceeded` | `--max-cost` reached | yes | yes, with a higher budget |
| `skipped` | Run halted before reaching this reference | yes | yes |

## Retry layers

**Layer 1 — per-request:** `_request_with_retry()` retries 429, 5xx, and network errors with exponential backoff + jitter, honoring `Retry-After`. `404` returns "no match". Any other 4xx raises `bad_request` immediately — replaying a rejected request only burns the backoff schedule.

**Layer 2 — record-level:** `retry` re-processes every record with `verified == false` and merges results into `{file}.json`. Each sidecar's counters accumulate onto its own history rather than the run-wide totals.

## Sidecar JSON schema

```json
{
  "report": "work/deep/research_init.md",
  "timestamp": "2026-07-07T15:00:00Z",
  "summary": {
    "total": 36,
    "verified": 29,
    "unverified": 0,
    "errored": 2,
    "ambiguous": 3,
    "not_found": 2,
    "skipped": 0,
    "live_calls": 8,
    "cache_hits": 12,
    "memo_hits": 4,
    "estimated_openalex_cost_usd": 0.0007
  },
  "references": [
    {
      "index": 1,
      "original_title": "...",
      "original_url": "https://...",
      "identifier": {"type": "doi", "value": "10.1234/example"},
      "dedup_key": "doi:10.1234/example",
      "verified": true,
      "error": null,
      "attempts": 1,
      "match_method": "singleton",
      "title_similarity": 1.0,
      "openalex": {
        "id": "https://openalex.org/W123",
        "doi": "https://doi.org/10.1234/example",
        "title": "...",
        "authors": ["..."],
        "publication_year": 2024,
        "venue": "...",
        "cited_by_count": 42,
        "oa_status": "gold",
        "oa_url": "https://..."
      },
      "cache_hit": false
    }
  ]
}
```

`error` values: `null`, `ambiguous`, `not_found`, `network_error`, `bad_request`, `rate_limited`, `budget_exceeded`, `skipped`.

`match_method` is `singleton`, `title_search`, or `not_found`. `cache_hit` marks a record served from the memo or the on-disk cache.
