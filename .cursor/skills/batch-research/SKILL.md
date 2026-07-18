---
name: batch-research
description: >-
  Multi-facet Valyu batch research: fast baseline, decompose into in-scope
  sub-ideas, parallel batch DeepResearch with async/retry and cost guardrails.
  Use for batch research, exploring multiple angles of one topic, or parallel
  sub-queries. Not for talk craft (enrich-research) or a single heavy deep-dive
  (deep-research).
---

# Batch Research

Decompose one topic into deeper facets, then run parallel Valyu DeepResearch.

**Not this skill:** talk storytelling/visuals → `enrich-research`. One hierarchical heavy dive → `deep-research`. Citation audit → `verify-references`. Quick cited lookup → Answer/Search via `.agents/skills/valyu-best-practices`.

**Runner:** `.cursor/skills/batch-research/scripts/research_runner.py`

| Command | Purpose |
|---|---|
| `single` | One task (`--no-wait`, `--max-cost`, `--mode`) |
| `batch` | Parallel batch from `ideas.json` |
| `status` | Poll + download results |
| `retry` | Re-run failed/cancelled from `manifest.json` |

Modes: `fast` ~$0.10 (~5 min) · `standard` ~$0.50 (~10–20 min) · `heavy` ~$2.50 (~90 min) · `max` ~$15. Default `--max-cost` $3.00.

No HITL on this path—use `deep-research` for plan/source review. Shared Valyu rules: `.cursor/rules/valyu-api.mdc`.

---

## Workflow

```
- [ ] 1 single --mode fast → output/research_init.md
- [ ] 2 Analyze → output/ideas.json (≤12 in-scope drill-downs)
- [ ] 3 batch (prefer --no-wait if ≥5 queries or mode > fast)
- [ ] 4 status → retry failures → summarize
- [ ] 5 (optional) verify-references
```

### 1. Baseline

Focused semantic query; no `site:` / boolean operators.

```bash
python .cursor/skills/batch-research/scripts/research_runner.py single \
  --query "TOPIC" --output "output/research_init.md" --mode fast
```

### 2. Ideation → `output/ideas.json`

Decompose the baseline — go **deeper**, not broader. Treat baseline headings as the allowed menu. Valyu rule: split multi-facet asks into separate queries (this skill’s purpose).

- Each query drills one existing facet (mechanism, comparison, evidence, edge cases, implementation).
- Keep each query concise and specific (prefer under ~400 chars); no search operators.
- **Litmus:** all ideas merged should still fit under the baseline’s top-level headings. No new parent domains.
- Prefer breadth *across* facets of the same subject; each query goes deep on its facet.

```json
{
  "main_topic": "Must match the baseline topic",
  "queries": [
    "Deeper drill-down into baseline facet 1",
    "Deeper drill-down into baseline facet 2"
  ]
}
```

Queries may also be `{"query": "..."}` objects (extra keys like `id`/`track` are ignored by the runner).

### 3. Batch

Default `--mode fast` for breadth. Escalate to `standard` (or heavier) only for denser facets after cost review—avoid `heavy`/`max` × N without explicit budget.

```bash
# Async (recommended for ≥5 queries or modes heavier than fast)
python .cursor/skills/batch-research/scripts/research_runner.py batch \
  --queries-file "output/ideas.json" --output-dir "output" \
  --name "Batch Research: TOPIC" --mode fast --no-wait --max-cost 5.00
```

Tell the user the Batch ID. Poll:

```bash
python .cursor/skills/batch-research/scripts/research_runner.py status \
  --batch-id "BATCH_ID" --output-dir "output"
```

`--no-wait` state is saved as `{output-dir}/active_batches.json`.

### 4. Retry & summarize

If `manifest.json` has failed/cancelled tasks:

```bash
python .cursor/skills/batch-research/scripts/research_runner.py retry \
  --manifest "output/manifest.json" --output-dir "output" \
  --mode fast --max-cost 2.00
```

Retry merges successes back into the original manifest. Summarize with filepath × major findings. Reports usually include `## Sources` for optional OpenAlex audit:

```bash
python .cursor/skills/verify-references/scripts/verify_references.py verify --max-cost 1.0
```

---

## Cost

Estimate: `num_queries × mode_cost`. Abort before API if over `--max-cost`. Buffer ~20%.

| Scenario | Est. | `--max-cost` |
|---|---|---|
| 10 × fast | $1 | $2 |
| 10 × standard | $5 | $7 |
| 12 × heavy | $30 | $35 |

---

## Practices

- Never hardcode/log `VALYU_API_KEY` (runner loads `.env`).
- Always pass `--max-cost`. Prefer `--no-wait` for large/slow batches.
- Retry failures before final summary.
- Source scope: `[valyu] categories` / `VALYU_CATEGORIES` → first token → `search.category`. Use `research` (or similar) for academic-leaning batches; omit for open-web breadth.
- Artifacts: `{output-dir}/manifest.json`, `{output-dir}/active_batches.json`, `output/active_tasks.json` (single `--no-wait`).
