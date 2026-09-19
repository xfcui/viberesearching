---
name: research-single-topic
description: >-
  Two-stage Valyu research for one high-quality full-scope report: repeatable
  fast init followed by one precisely refined heavy run, optional HITL, and a
  coverage audit. Use when the user wants depth in one report without parallel
  facet fan-out. For depth plus breadth use research-comprehensive.
---

# Single-Topic Research

**Stages: fast init → heavy refined.**

Follow `.cursor/rules/valyu-api.mdc` for shared stage, source, cost, async,
scope, and recovery policy. Outputs default to `work/deep/`.

Use `research-comprehensive` when the user also wants parallel facet reports;
use `research-multi-angle` when parallel facets are the primary deliverable.

## Workflow

```text
- [ ] 1 Fast init → work/deep/research_init.md
- [ ] 2 Refine whole topic → work/deep/research_idea.md
- [ ] 3 Heavy refined → work/deep/research_deep.md
- [ ] 4 Coverage audit and synthesis
- [ ] 5 Optional HITL / citation audit
```

Check `work/deep/tmp_state.json` first and resume matching live work.

### 1. Fast init

```bash
python .cursor/skills/research-single-topic/scripts/research_runner.py run \
  --query "MAIN_TOPIC with a dated recent-results window" \
  --output "work/deep/research_init.md" \
  --mode fast --max-cost 1.00
```

Read it. Repeat cheaply until the sense, framing, terminology, and
substantive headings are correct.

### 2. Research idea

Write `work/deep/research_idea.md`:

```markdown
# Single-Topic Research Idea

**Main Topic:** [unchanged baseline topic]
**Scope Terms:** [precise terms from the baseline]
**Coverage Facets:** [retained substantive baseline H2s]
**Recency Window:** [dated window]
**Deliberately Dropped:** [out-of-emphasis facets, or none]
**Out of Scope:** [adjacent drift attractors]
**Evidence Bar:** [named primary sources, quantitative values, industry signals]
**Formulated Query:** [same whole topic, made precise]
```

Go more precise, not narrower.

### 3. Heavy refined

```bash
python .cursor/skills/research-single-topic/scripts/research_runner.py run \
  --query "FORMULATED_FULL_SCOPE_QUERY" \
  --output "work/deep/research_deep.md" \
  --main-topic "MAIN_TOPIC" \
  --mode heavy --no-wait --max-cost 5.00
```

Tell the user the task ID, then collect:

```bash
python .cursor/skills/research-single-topic/scripts/research_runner.py status \
  --task-id "TASK_ID" --output "work/deep/research_deep.md"
```

### 4. Coverage audit

```bash
python .cursor/skills/research-single-topic/scripts/research_runner.py enrich-check \
  --baseline "work/deep/research_init.md" \
  --deep "work/deep/research_deep.md"
```

Add one `--allow-drop "SUBSTRING"` per deliberate drop. Treat the result as a
heading heuristic, then judge depth gains, recency, boundaries, and citation
integrity by reading both reports.

Synthesize what heavy strengthened, corrected, dropped, or added. If broad
parallel follow-up is now needed, hand the artifacts to
`research-comprehensive` instead of hiding the new scope inside this skill.

## Optional HITL

Add `--hitl` to the heavy `run`. On a checkpoint, present
`tmp_checkpoint.json`; write the user's valid JSON response to
`tmp_checkpoint_response.json`. Invalid JSON remains paused.

For an asynchronously paused task:

```bash
python .cursor/skills/research-single-topic/scripts/research_runner.py respond \
  --task-id "TASK_ID" \
  --response-file "work/deep/tmp_checkpoint_response.json"
```
