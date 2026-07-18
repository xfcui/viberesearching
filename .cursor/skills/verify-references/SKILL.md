---
name: verify-references
description: >-
  Verify and enrich research report citations via OpenAlex. Parses ## Sources
  from markdown reports, deduplicates lookups, writes audit-only {file}.json
  sidecars, supports retry. Use after deep-research or batch-research when the
  user wants reference verification or bibliographic enrichment.
---

# Verify References

Resolve citations in research reports against OpenAlex. Reads `## Sources` from markdown (default `output/*.md`), writes audit-only `{file}.json` sidecars. **Never modifies reports.** Works best when Valyu reports include a `## Sources` block; batch `manifest.json` source lists are not the verify input format.

**Runner:** `.cursor/skills/verify-references/scripts/verify_references.py`

| Command | Purpose |
|---|---|
| `verify` | Verify refs in report `.md` files |
| `retry` | Re-run unverified/errored records from sidecars |

| Flag | Default / notes |
|---|---|
| `--input` | `output/*.md` |
| `--rate` | 5 req/s |
| `--sim-threshold` | 0.8 (title search) |
| `--max-cost` | Abort if OpenAlex estimate exceeds |
| `--retries` | 4 (429/5xx/network) |
| `--cache` | `output/openalex_cache.json` |
| `--no-cache` / `--refresh-cache` | Cache control |
| `--force-search` | (`retry`) skip singleton; force title search |
| `--refs` | (`retry`) sidecar path/glob |

Details: [reference.md](reference.md) (progress formats, cost model, sidecar schema).

---

## Workflow

Optional final phase after `deep-research` / `batch-research` / `enrich-research`. Run in the foreground and **relay per-reference progress** to the user.

### 1. Verify

```bash
python .cursor/skills/verify-references/scripts/verify_references.py verify --max-cost 1.0
```

Single report:

```bash
python .cursor/skills/verify-references/scripts/verify_references.py verify \
  --input "output/research_deep.md" --max-cost 1.0
```

### 2. Retry failures

```bash
python .cursor/skills/verify-references/scripts/verify_references.py retry
```

Or:

```bash
python .cursor/skills/verify-references/scripts/verify_references.py retry \
  --input "output/research_init.md" --force-search
```

Retry merges into existing sidecars; verified records stay untouched.

---

## Practices

- **Audit-only** — enrichment only in `{file}.json`.
- Load `OPENALEX_API_KEY` from `.env`; never log the key.
- Prefer `--rate 5` + `--max-cost`; use `retry` next day if daily budget is exhausted.
- Retry errored refs before presenting final verification summary.
- Cache file is machine-generated; keep gitignored.
