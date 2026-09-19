---
name: batch-research
description: >-
  Multi-facet Valyu batch research: fast baseline, decompose into in-scope
  sub-ideas, then up to 12 parallel standard DeepResearch tasks with scope
  anchoring, async/retry, and cost guardrails. Use for batch research,
  exploring multiple angles of one topic, or parallel sub-queries. Not for talk
  craft (enrich-research) or a single heavy deep-dive (deep-research).
---

# Batch Research

**Shape: one fast baseline + up to 12 standard researches.** Outputs under `work/batch/`.

**Not this skill:** talk storytelling/visuals → `enrich-research`. One hierarchical heavy dive → `deep-research`. Citation audit → `verify-references`. Quick cited lookup → the Valyu Answer/Search API directly.

**Runner:** `.cursor/skills/batch-research/scripts/research_runner.py`

| Command | Purpose |
|---|---|
| `single` | One task (`--main-topic`, `--no-wait`, `--max-cost`, `--mode`) |
| `batch` | Parallel batch from `ideas.json` (`--max-queries`, default 12) |
| `status` | Poll + download results |
| `retry` | Re-run failed/cancelled from `manifest.json` |
| `scope-check` | Local drift audit of finished reports (no API cost) |

Baseline is `fast` (~$0.10); the fan-out is `standard` (~$0.50, ~10–20 min each). `heavy` / `max` stay available as CLI modes but are not this workflow — `12 × heavy` is $30.

No HITL on this path—use `deep-research` for plan/source review. Shared Valyu rules: `.cursor/rules/valyu-api.mdc` (§10 covers scope anchoring).

---

## Workflow

```
- [ ] 1 single --mode fast → work/batch/research_init.md
- [ ] 2 Analyze → work/batch/ideas.json (≤12 anchored drill-downs)
- [ ] 3 batch --mode standard --no-wait
- [ ] 4 status → retry failures → summarize
- [ ] 5 (optional) scope-check + verify-references
```

### 1. Baseline

Focused semantic query; no `site:` / boolean operators. No anchor — the baseline *is* the topic.

```bash
python .cursor/skills/batch-research/scripts/research_runner.py single \
  --query "TOPIC" --output "work/batch/research_init.md" --mode fast
```

### 2. Ideation → `work/batch/ideas.json`

Decompose the baseline — go **deeper**, not broader. Treat baseline headings as the allowed menu. Valyu rule: split multi-facet asks into separate queries (this skill's purpose).

- Each query drills one existing facet (mechanism, comparison, evidence, edge cases, implementation).
- Keep each query concise and specific (prefer under ~250 chars so the anchor clause still fits under ~400); no search operators.
- Declare `anchor_headings` from the baseline's H2s and give every query an `anchor`.
- **Ineligible anchors:** `Executive Summary`, `Conclusion`, `Sources`, and any `Applications` / `Future Directions` / `Recent Developments` / `Emerging` heading. These are catch-alls — anchoring to one is how a scan-RNN baseline ends up spawning vision and genomics reports.
- Apply the three-test gate in `.cursor/rules/valyu-api.mdc` §10: anchor, subject, transfer.

```json
{
  "main_topic": "Must match the baseline topic",
  "anchor_terms": ["distinctive phrase 1", "distinctive phrase 2"],
  "anchor_headings": ["1. Baseline heading", "2. Baseline heading"],
  "queries": [
    {"id": "Q01", "anchor": "1. Baseline heading", "query": "Deeper drill-down into that facet"},
    {"id": "Q02", "anchor": "2. Baseline heading", "query": "Deeper drill-down into that facet"}
  ]
}
```

Plain `"queries": ["...", "..."]` still parses, but runs unanchored with a warning — prefer the anchored form.

### 3. Batch

`standard` is the default mode and 12 the default cap; both abort before the API call if exceeded.

```bash
python .cursor/skills/batch-research/scripts/research_runner.py batch \
  --queries-file "work/batch/ideas.json" --output-dir "work/batch" \
  --name "Batch Research: TOPIC" --mode standard --no-wait --max-cost 7.00
```

The runner attaches `main_topic` to every submitted query and rejects queries that share no distinctive terminology with it. `--allow-drift` downgrades those errors; `--no-anchor` skips the attachment entirely.

Use `--no-wait`: 12 standard tasks take well over 10 minutes. Tell the user the Batch ID, then poll:

```bash
python .cursor/skills/batch-research/scripts/research_runner.py status \
  --batch-id "BATCH_ID" --output-dir "work/batch"
```

`--no-wait` state lives in `work/batch/tmp_state.json` and is removed automatically once every task succeeds.

### 4. Retry & summarize

If `manifest.json` has failed/cancelled tasks (temp state is kept precisely for this):

```bash
python .cursor/skills/batch-research/scripts/research_runner.py retry \
  --manifest "work/batch/manifest.json" --output-dir "work/batch" \
  --mode standard --max-cost 2.00
```

Retry reuses each task's stored anchor and merges successes back into the original manifest. Summarize with filepath × major findings.

### 5. Optional audits

```bash
# Free local drift audit: report headings vs. their anchors
python .cursor/skills/batch-research/scripts/research_runner.py scope-check \
  --manifest "work/batch/manifest.json" --queries-file "work/batch/ideas.json"

# OpenAlex citation audit
python .cursor/skills/verify-references/scripts/verify_references.py verify \
  --input "work/batch/*.md" --max-cost 1.0
```

---

## Cost

Estimate: `num_queries × mode_cost`. Abort before API if over `--max-cost`. Buffer ~20%.

| Scenario | Est. | `--max-cost` |
|---|---|---|
| Baseline (1 × fast) | $0.10 | $1 |
| 6 × standard | $3 | $4 |
| 12 × standard (cap) | $6 | $7 |

---

## Practices

- Never hardcode/log `VALYU_API_KEY` (runner loads `.env`).
- Always pass `--max-cost`. Always use `--no-wait` for the fan-out.
- Keep the cap: 12 queries. Raise it only with an explicit budget (`--max-queries N`, or `0` for uncapped).
- Retry failures before final summary.
- Source scope: `[valyu] categories` / `VALYU_CATEGORIES` → first token → `search.category`. Use `research` (or similar) for academic-leaning batches; omit for open-web breadth.
- Artifacts in `work/batch/`: `research_init.md`, `ideas.json`, `researchNN_*.md`, `manifest.json`, plus `tmp_state.json` while a run is in flight.
