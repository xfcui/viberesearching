---
name: research-comprehensive
description: >-
  End-to-end Valyu research on one topic: fast init, one full-scope heavy
  refinement, then up to 12 standard facet reports. Uses research sources
  throughout and writes one topic-named work directory. Use when the user
  wants both a deep report and broad parallel coverage. Not for only one
  full-scope report, only parallel facets, or enrichment of supplied content.
---

# Comprehensive Research

**Stages: fast init → heavy refined → standard fan-out.**

Follow `.cursor/rules/valyu-api.mdc` for the shared stage, source, cost,
async, scope, and recovery contract. This skill only orchestrates all three
stages in `work/<topic-slug>/`.

Route narrower outcomes elsewhere:

- one full-scope report → `research-single-topic`;
- parallel facet reports → `research-multi-angle`;
- strengthen supplied content → `research-enrich`;
- citation audit only → `research-verify`.

## Artifacts

```text
work/<topic-slug>/
├── research_init.md
├── research_idea.md
├── research_deep.md
├── ideas.json
├── researchNN_*.md
├── manifest.json
└── tmp_state.json
```

Before submitting, inspect existing artifacts and `tmp_state.json`. Resume
matching live work and reuse completed valid stages instead of paying twice.

## Workflow

```text
- [ ] 1 Fast init → research_init.md
- [ ] 2 Refine the whole topic → research_idea.md
- [ ] 3 Heavy refined → research_deep.md
- [ ] 4 Coverage audit
- [ ] 5 Build anchored gaps → ideas.json
- [ ] 6 Standard fan-out → reports + manifest
- [ ] 7 Scope audit and synthesis
```

### 1. Fast init

Agree on the topic slug. Pin research sources explicitly:

```bash
VALYU_CATEGORIES=research python \
  .cursor/skills/research-single-topic/scripts/research_runner.py run \
  --query "MAIN_TOPIC with a dated recent-results window" \
  --output "work/<topic-slug>/research_init.md" \
  --mode fast --max-cost 1.00
```

Read and repeat until the sense, framing, terminology, and headings are
correct.

### 2. Heavy refined

Write `research_idea.md` with the unchanged main topic, scope terms, retained
baseline facets, dated recency window, deliberate drops, boundaries, evidence
bar, and one full-scope formulated query.

```bash
VALYU_CATEGORIES=research python \
  .cursor/skills/research-single-topic/scripts/research_runner.py run \
  --query "FORMULATED_FULL_SCOPE_QUERY" \
  --output "work/<topic-slug>/research_deep.md" \
  --main-topic "MAIN_TOPIC" \
  --mode heavy --no-wait --max-cost 5.00
```

Collect with `status`, then run:

```bash
python .cursor/skills/research-single-topic/scripts/research_runner.py enrich-check \
  --baseline "work/<topic-slug>/research_init.md" \
  --deep "work/<topic-slug>/research_deep.md"
```

Read the heuristic output and both reports. Record dropped baseline facets,
thin evidence, unresolved claims, and off-topic additions.

### 3. Standard fan-out

Build `ideas.json` from heavy-report headings plus eligible baseline headings
for dropped facets. Use at most 12 non-overlapping queries. Make gaps from the
coverage audit the priority; do not launch a generic second survey.

```bash
VALYU_CATEGORIES=research python \
  .cursor/skills/research-multi-angle/scripts/research_runner.py batch \
  --queries-file "work/<topic-slug>/ideas.json" \
  --output-dir "work/<topic-slug>" \
  --name "Comprehensive Research: MAIN_TOPIC" \
  --mode standard --no-wait --max-cost 7.00
```

Collect with `status`; retry failed/cancelled entries with the same research
source profile and a calculated cost limit. Run `scope-check` before
synthesis.

## Synthesis

Compare fast init → heavy refined → facet reports. Report:

- which baseline facets became stronger;
- what fan-out added beyond the heavy report;
- strongest recent academic evidence;
- industry signals available **within papers and preprints**;
- disagreements, unresolved gaps, drift, and source limitations;
- report path → major finding.

One probe + heavy + 12 standard tasks has a planned base cost of about $8.60.
Repeated probes, retries, and citation verification add spend.
