---
name: deep-research
description: >-
  Hierarchical Valyu DeepResearch: fast baseline, one in-scope deep-dive query,
  then one heavy research with async polling, optional HITL, scope anchoring,
  and cost guardrails. Use for deep research, fast-vs-heavy comparison, or a
  single hierarchical dive. Not for multi-facet parallel batches
  (batch-research) or talk craft (enrich-research).
---

# Deep Research

**Shape: one fast baseline + exactly one heavy dive.** Outputs under `work/deep/`.

**Not this skill:** many parallel facets → `batch-research`. Talk storytelling/visuals → `enrich-research`. Citation audit → `verify-references`. Quick cited lookup → the Valyu Answer/Search API directly (do not spend DeepResearch on that).

**Runner:** `.cursor/skills/deep-research/scripts/research_runner.py`

| Command | Purpose |
|---|---|
| `run` | Create task (`--main-topic`, `--no-wait`, `--hitl`, `--max-cost`, `--mode`) |
| `status` | Poll + download |
| `respond` | Reply to HITL checkpoint |

Baseline is `fast` (~$0.10, ~5 min); the dive is `heavy` (~$2.50, ~90 min). Default `--max-cost` $3.00. `standard` and `max` remain valid CLI modes but are not part of this workflow.

Shared Valyu rules: `.cursor/rules/valyu-api.mdc` (§10 covers scope anchoring).

---

## Workflow

```
- [ ] 1 run --mode fast → work/deep/research_init.md
- [ ] 2 Analyze → work/deep/deep_research_idea.md (one in-scope drill-down)
- [ ] 3 run --mode heavy --main-topic --no-wait → work/deep/research_deep.md
- [ ] 4 status → synthesize fast vs heavy
- [ ] 5 (optional) verify-references / HITL if enabled
```

### 1. Baseline

Write a focused natural-language query (specific terminology, timeframe if useful). No `site:` / boolean operators. No `--main-topic` here — the baseline *is* the topic.

```bash
python .cursor/skills/deep-research/scripts/research_runner.py run \
  --query "MAIN_TOPIC" --output "work/deep/research_init.md" --mode fast
```

### 2. Deep ideation → `work/deep/deep_research_idea.md`

Go **deeper**, not broader. Pick the densest facet already central in the baseline. Valyu rule: one topic per query—do not pack a survey essay into the deep query.

- Query must be a strict subset of the main topic (more detail/mechanism/comparison/evidence on that facet).
- Prefer concise, semantic phrasing (under ~250 chars, so the anchor clause still fits under ~400).
- Anchor heading must be a **substantive** baseline heading. `Executive Summary`, `Conclusion`, `Sources`, and any `Applications` / `Future Directions` / `Recent Developments` / `Emerging` heading are ineligible — they are catch-alls that license unlimited breadth.
- Apply the three-test gate in `.cursor/rules/valyu-api.mdc` §10: anchor, subject, transfer.

```markdown
# Deep Research Idea

**Main Topic:** [same as baseline]
**Anchor Heading:** [exact baseline heading — must be substantive]
**Anchor Terms:** [2–4 distinctive phrases from the baseline]
**Formulated Query:** [narrowed heavy-mode query]

### Context & Justification
- [Why this facet needs depth]
- [Gaps left in the baseline for that facet]

### Scope Check
- Anchor test: [heading is substantive, not a catch-all]
- Subject test: [subject is still the main topic's subject]
- Transfer test: [would not fit a report on a different topic]
```

### 3. Heavy research

Pass `--main-topic` so the dive stays inside the baseline, and prefer `--no-wait` (heavy often ~90 min):

```bash
python .cursor/skills/deep-research/scripts/research_runner.py run \
  --query "FORMULATED_QUERY" --output "work/deep/research_deep.md" \
  --main-topic "MAIN_TOPIC" --mode heavy --no-wait --max-cost 5.00
```

The runner checks the query against the main topic and aborts on drift before spending anything; `--allow-drift` overrides when the wording is unusual but the scope is genuinely right.

Tell the user the Task ID. Poll:

```bash
python .cursor/skills/deep-research/scripts/research_runner.py status \
  --task-id "TASK_ID" --output "work/deep/research_deep.md"
```

On success the runner removes `work/deep/tmp_*.json` automatically.

### 4. Synthesis

Compare `research_init.md` vs `research_deep.md`: structure/depth, source quality, fast vs heavy cost-benefit. Flag any deep-report section that has no home under the anchor heading — that is drift worth reporting. Completed reports typically include a `## Sources` block for optional verification.

### 5. Optional reference verification

```bash
python .cursor/skills/verify-references/scripts/verify_references.py verify \
  --input "work/deep/*.md" --max-cost 1.0
# then if needed:
python .cursor/skills/verify-references/scripts/verify_references.py retry \
  --input "work/deep/*.md"
```

---

## HITL (optional)

```bash
python .cursor/skills/deep-research/scripts/research_runner.py run \
  --query "TOPIC" --output "work/deep/report.md" --mode heavy --hitl
```

On pause: read `work/deep/tmp_checkpoint.json` → present to user → write `work/deep/tmp_checkpoint_response.json`.

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
  --task-id "TASK_ID" --response-file "work/deep/tmp_checkpoint_response.json"
```

---

## Cost & practices

| Stage | Mode | Est. | Duration | `--max-cost` |
|---|---|---|---|---|
| Baseline | fast | $0.10 | ~5 min | $1 |
| Dive | heavy | $2.50 | ~90 min | $5 |

- Never hardcode/log `VALYU_API_KEY`. Always pass `--max-cost`.
- `--no-wait` for the heavy dive; state in `work/deep/tmp_state.json`, auto-removed on success.
- Always pass `--main-topic` on the dive. Only the baseline runs unanchored.
- Source scope today: `[valyu] categories` / `VALYU_CATEGORIES` → first token → `search.category`. Omit for all sources.
- Quick lookups → Valyu Answer/Search, not this skill (see `.cursor/rules/valyu-api.mdc` §0).
