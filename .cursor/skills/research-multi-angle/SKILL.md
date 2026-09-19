---
name: research-multi-angle
description: >-
  Two-stage Valyu research for parallel coverage: one fast init followed by up
  to 12 anchored standard facet reports with async collection, retry, and
  scope audit. Use when parallel angles are the deliverable and no heavy
  full-scope report is needed. For both depth and breadth use
  research-comprehensive.
---

# Multi-Angle Research

**Stages: fast init → standard fan-out.**

Follow `.cursor/rules/valyu-api.mdc` for shared stage, source, cost, async,
scope, and recovery policy. Outputs default to `work/batch/`.

Use `research-single-topic` for one heavy report and
`research-comprehensive` for heavy plus fan-out.

## Workflow

```text
- [ ] 1 Fast init → work/batch/research_init.md
- [ ] 2 Build anchored facets → work/batch/ideas.json
- [ ] 3 Standard fan-out → reports + manifest
- [ ] 4 Collect, retry failures, scope-audit, summarize
```

Check `work/batch/tmp_state.json` first and resume matching live work.

### 1. Fast init

```bash
python .cursor/skills/research-multi-angle/scripts/research_runner.py single \
  --query "MAIN_TOPIC with a dated recent-results window" \
  --output "work/batch/research_init.md" \
  --mode fast --max-cost 1.00
```

Read and repeat until it identifies the correct topic, terminology, and
substantive facets.

### 2. Ideas

Create at most 12 non-overlapping strict subsets of the baseline:

```json
{
  "main_topic": "Same topic as the promoted fast init",
  "anchor_terms": ["distinctive phrase 1", "distinctive phrase 2"],
  "anchor_headings": ["1. Substantive heading", "2. Substantive heading"],
  "queries": [
    {
      "id": "Q01",
      "anchor": "1. Substantive heading",
      "query": "Focused drill-down into this facet"
    }
  ]
}
```

### 3. Standard fan-out

```bash
python .cursor/skills/research-multi-angle/scripts/research_runner.py batch \
  --queries-file "work/batch/ideas.json" \
  --output-dir "work/batch" \
  --name "Multi-Angle Research: MAIN_TOPIC" \
  --mode standard --no-wait --max-cost 7.00
```

Tell the user the batch ID. Collect:

```bash
python .cursor/skills/research-multi-angle/scripts/research_runner.py status \
  --batch-id "BATCH_ID" --output-dir "work/batch"
```

For failures, calculate the retry limit from
`failed_count × $0.50` plus a small buffer:

```bash
python .cursor/skills/research-multi-angle/scripts/research_runner.py retry \
  --manifest "work/batch/manifest.json" \
  --output-dir "work/batch" \
  --mode standard --no-wait --max-cost <calculated-limit>
```

Use `--no-wait` when five or more retries are submitted; otherwise synchronous
retry is acceptable.

### 4. Audit and summarize

```bash
python .cursor/skills/research-multi-angle/scripts/research_runner.py scope-check \
  --manifest "work/batch/manifest.json" \
  --queries-file "work/batch/ideas.json"
```

Retry failures before final reporting. Summarize each manifest entry by
filepath, anchor, and major finding; call out scope flags and unresolved
facets.

`single --no-wait` is supported for direct CLI use; collect it with the
runner's `task-status` command.
