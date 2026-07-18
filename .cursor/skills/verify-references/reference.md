# Verify References — Reference

## Progress output

During `verify`, each reference is logged as it is resolved:

```
Verifying references in 2 report(s) (48 reference(s) total)...

  Report 1/2: output/research_init.md (36 reference(s))
    [1/36] [1] Attention Is All You Need -> verified (singleton)
    [2/36] [2] BERT: Pre-training of Deep Bidirectional… -> cache hit
    [3/36] [3] Some Obscure Paper Title -> ambiguous
    ...
    refs=36 verified=29 ambiguous=3 not_found=2 errored=2 -> research_init.json

  Report 2/2: output/research_deep.md (12 reference(s))
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

Status labels: `verified (singleton|title_search)`, `cache hit`, `ambiguous`, `not_found`, `rate_limited`, `network_error`, `recovered (...)`.

## De-duplication & caching

1. **Dedup key** (priority): DOI → PMID → PMCID → normalized title
2. **In-run memo**: one OpenAlex lookup per distinct work across all files in a run
3. **Persistent cache** at `output/openalex_cache.json` (or beside `--input` outputs): cross-run reuse

End-of-run summary reports `live_calls`, `cache_hits`, and `memo_hits`.

## OpenAlex cost model

Configure `[openalex] api_key` in `.env` (or `OPENALEX_API_KEY`). Free key: [openalex.org/settings/api](https://openalex.org/settings/api).

| Lookup type | Approx. cost | Notes |
|---|---|---|
| Singleton (DOI / PMID / PMCID / arXiv ID) | $0 | Free, unlimited |
| Title filter (`filter=title.search:`) | $0.0001/call | Prefer over full `search=` |
| Full-text search | $0.001/call | Avoid unless necessary |

Free tier: ~$1/day with an API key. Use `--max-cost` and `--rate 5`.

## Retry layers

**Layer 1 — per-request:** `_request_with_retry()` handles 429, 5xx, and network errors with exponential backoff + jitter. Honors `Retry-After`. `404` is not retried. Budget exhaustion stops with partial results.

**Layer 2 — record-level:** `retry` re-processes only `verified == false` or `error` set, then merges into `{file}.json`.

## Sidecar JSON schema

```json
{
  "report": "output/research_init.md",
  "timestamp": "2026-07-07T15:00:00Z",
  "summary": {
    "total": 36,
    "verified": 29,
    "unverified": 0,
    "errored": 2,
    "ambiguous": 3,
    "not_found": 2,
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

`error` values: `null`, `rate_limited`, `network_error`, `ambiguous`, `not_found`.
