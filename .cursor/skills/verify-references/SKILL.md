---
name: verify-references
description: >-
  Verify and enrich research report citations via OpenAlex. Parses ## Sources
  from markdown reports, deduplicates lookups, writes audit-only {file}.json
  sidecars, supports retry. Use after deep-research or batch-research when the
  user wants reference verification or bibliographic enrichment.
---

# Verify References

Resolve citations in research reports against OpenAlex. Reads the `## Sources` (or `## References`) block from markdown (default `work/**/*.md`), writes audit-only `{file}.json` sidecars. **Never modifies reports.** Files without a `## Sources` block are skipped, so ideation notes and briefs get no sidecar; batch `manifest.json` source lists are not the verify input format.

**Runner:** `.cursor/skills/verify-references/scripts/verify_references.py`

| Command | Purpose |
|---|---|
| `verify` | Verify refs in report `.md` files |
| `retry` | Re-run unverified/errored records from sidecars |

| Flag | Default / notes |
|---|---|
| `--input` | `work/**/*.md` (recursive) |
| `--rate` | 5 req/s |
| `--sim-threshold` | 0.8 (title search) |
| `--max-cost` | Abort if OpenAlex estimate exceeds |
| `--retries` | 4 (429/5xx/network only) |
| `--cache` | `auto` — one `openalex_cache.json` per report directory |
| `--no-cache` / `--refresh-cache` | Cache control |
| `--force-search` | (`retry`) skip singleton; force title search |
| `--refs` | (`retry`) sidecar path/glob |

Identifiers resolve for free: DOIs, PMIDs, and arXiv IDs (looked up through their `10.48550/arXiv.*` DOI). Everything else falls back to a $0.0001 title search.

Details: [reference.md](reference.md) (progress formats, cost model, sidecar schema).

---

## Workflow

Optional final phase after `deep-research` / `batch-research` / `enrich-research`. Run in the foreground and **relay per-reference progress** to the user.

### 1. Verify

Scope `--input` to the skill directory you just ran; the bare default sweeps every report under `work/`.

```bash
python .cursor/skills/verify-references/scripts/verify_references.py verify \
  --input "work/batch/*.md" --max-cost 1.0
```

Single report:

```bash
python .cursor/skills/verify-references/scripts/verify_references.py verify \
  --input "work/deep/research_deep.md" --max-cost 1.0
```

### 2. Retry failures

```bash
python .cursor/skills/verify-references/scripts/verify_references.py retry \
  --input "work/batch/*.md"
```

Or:

```bash
python .cursor/skills/verify-references/scripts/verify_references.py retry \
  --input "work/batch/research_init.md" --force-search
```

Retry merges into existing sidecars; verified records stay untouched. Anything still unresolved is re-queried — only positives are cached, so `retry` never short-circuits on a stale miss.

Reach for `retry` when a run reports `rate_limited`, `budget_exceeded`, `skipped`, or `network_error`. A `not_found` on a blog or vendor page usually means OpenAlex has no such record, and repeat runs will not change that.

---

## Practices

- **Audit-only** — enrichment only in `{file}.json`.
- `OPENALEX_API_KEY` is optional (it raises the daily cap); `OPENALEX_MAILTO` joins the polite pool. Load both from `.env`; never log the key.
- Prefer `--rate 5` + `--max-cost`; use `retry` next day if daily budget is exhausted.
- Retry errored refs before presenting final verification summary.
- Cache files are machine-generated; keep gitignored.
