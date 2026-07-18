---
name: deep-research
description: >-
  Hierarchical Valyu DeepResearch: fast baseline, one in-scope deep-dive query,
  then heavy (or max) research with async polling, optional HITL, and cost
  guardrails. Use for deep research, fast-vs-heavy comparison, or a single
  hierarchical dive. Not for multi-facet parallel batches (batch-research) or
  talk craft (enrich-research).
---

# Deep Research

One topic → fast baseline → one narrowed deep query → heavy research. Outputs under `output/`.

**Not this skill:** many parallel facets → `batch-research`. Talk storytelling/visuals → `enrich-research`. Citation audit → `verify-references`. Quick cited lookup → Answer/Search via `.agents/skills/valyu-best-practices` (do not spend DeepResearch on that).

**Runner:** `.cursor/skills/deep-research/scripts/research_runner.py`

| Command | Purpose |
|---|---|
| `run` | Create task (`--no-wait`, `--hitl`, `--max-cost`, `--mode`) |
| `status` | Poll + download |
| `respond` | Reply to HITL checkpoint |

Modes: `fast` ~$0.10 (~5 min) · `standard` ~$0.50 (~10–20 min) · `heavy` ~$2.50 (~90 min) · `max` ~$15 (SDK mode; longest). Default `--max-cost` $3.00.

Shared Valyu rules: `.cursor/rules/valyu-api.mdc`.

---

## Workflow

```
- [ ] 1 run --mode fast → output/research_init.md
- [ ] 2 Analyze → output/deep_research_idea.md (one in-scope drill-down)
- [ ] 3 run --mode heavy --no-wait → output/research_deep.md
- [ ] 4 status → synthesize fast vs heavy
- [ ] 5 (optional) verify-references / HITL if enabled
```

### 1. Baseline

Write a focused natural-language query (specific terminology, timeframe if useful). No `site:` / boolean operators.

```bash
python .cursor/skills/deep-research/scripts/research_runner.py run \
  --query "MAIN_TOPIC" --output "output/research_init.md" --mode fast
```

### 2. Deep ideation → `output/deep_research_idea.md`

Go **deeper**, not broader. Pick the densest facet already central in the baseline. Valyu rule: one topic per query—do not pack a survey essay into the deep query.

- Query must be a strict subset of the main topic (more detail/mechanism/comparison/evidence on that facet).
- Prefer concise, semantic phrasing (under ~400 chars when practical).
- **Litmus:** every plausible deep-report section fits under one existing baseline heading. No new top-level domains.

```markdown
# Deep Research Idea

**Main Topic:** [same as baseline]
**Anchor Section:** [exact baseline heading]
**Formulated Query:** [narrowed heavy-mode query]

### Context & Justification
- [Why this facet needs depth]
- [Gaps left in the baseline for that facet]

### Scope Check
- In scope: [yes — which baseline heading]
- New top-level domains vs baseline: none
```

### 3. Heavy research

Prefer `--no-wait` for heavy/max (`heavy` often ~90 min):

```bash
python .cursor/skills/deep-research/scripts/research_runner.py run \
  --query "FORMULATED_QUERY" --output "output/research_deep.md" \
  --mode heavy --no-wait --max-cost 5.00
```

Tell the user the Task ID. Poll:

```bash
python .cursor/skills/deep-research/scripts/research_runner.py status \
  --task-id "TASK_ID" --output "output/research_deep.md"
```

### 4. Synthesis

Compare `research_init.md` vs `research_deep.md`: structure/depth, source quality, fast vs heavy cost-benefit. Completed reports typically include a `## Sources` block for optional verification.

### 5. Optional reference verification

```bash
python .cursor/skills/verify-references/scripts/verify_references.py verify --max-cost 1.0
# then if needed:
python .cursor/skills/verify-references/scripts/verify_references.py retry
```

---

## HITL (optional)

```bash
python .cursor/skills/deep-research/scripts/research_runner.py run \
  --query "TOPIC" --output "output/report.md" --mode heavy --hitl
```

On pause: read `output/checkpoint.json` → present to user → write `output/checkpoint_response.json`.

Examples:
```json
{"approved": true}
```
```json
{"included_domains": ["arxiv.org", "nature.com"], "excluded_domains": ["reddit.com"]}
```

If `--no-wait` and status is `awaiting_input`:

```bash
python .cursor/skills/deep-research/scripts/research_runner.py respond \
  --task-id "TASK_ID" --response-file "output/checkpoint_response.json"
```

---

## Cost & practices

| Mode | Est. | Duration | `--max-cost` |
|---|---|---|---|
| fast | $0.10 | ~5 min | $1 |
| standard | $0.50 | ~10–20 min | $2 |
| heavy | $2.50 | ~90 min | $5 |
| max | $15 | longest | $20 |

- Never hardcode/log `VALYU_API_KEY`. Always pass `--max-cost`.
- `--no-wait` for heavy/max; state in `output/active_tasks.json`.
- Source scope today: `[valyu] categories` / `VALYU_CATEGORIES` → first token → `search.category`. Omit for all sources.
- `max` is SDK-supported in this repo (beyond some vendored three-mode tables).
- Quick lookups → Answer/Search in `valyu-best-practices`, not this skill.
