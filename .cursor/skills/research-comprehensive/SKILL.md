---
name: research-comprehensive
description: >-
  End-to-end Valyu research on one topic: a fast baseline, one refined heavy
  full-scope report, then up to 12 standard facet drill-downs. Uses research
  sources throughout and emphasizes recent academic and industry advances.
  Use for comprehensive topic research that needs both depth and breadth. Not
  for a single deep dive, batch-only exploration, or talk craft.
---

# Comprehensive Research

**Shape: one repeatable fast probe → one full-scope heavy report → up to 12
standard drill-downs.** Put every artifact in one user-approved,
topic-named directory: `work/<topic-slug>/`.

Reuse the existing runners:

- Single fast/heavy tasks:
  `.cursor/skills/research-single-topic/scripts/research_runner.py`
- Standard batch:
  `.cursor/skills/research-multi-angle/scripts/research_runner.py`

**Not this skill:** fast + heavy only → `research-single-topic`. Fast +
parallel facets only → `research-multi-angle`. Enrich supplied content →
`research-enrich`. Citation audit only → `research-verify`.

## Research emphasis

Unless the user asks otherwise, every query should target **recent advances
in academia and industry**:

| Prefer | De-emphasize |
| --- | --- |
| Results, mechanisms, and architectures from roughly the last three years | Regulation, approval pathways, and policy surveys |
| Named papers, labs, groups, and quantitative benchmark deltas | Safety, toxicology, risk, security, and compliance as standalone subjects |
| Industry platforms, products, pipelines, partnerships, and deployment evidence | Market-size forecasts and generic vendor landscapes |

Safety, security, regulation, and market context belong only where they
explain a technical advance or decisive result. Put recency directly in each
query as a dated constraint such as `2024–2026 results`. Never use `Recent
Developments` or `Emerging` as batch anchors.

## Source contract

Pin `VALYU_CATEGORIES=research` on **every research submission**, even when
`.env` already says `categories = research`. This makes the source choice
explicit and stable if `.env` later changes.

This pin limits retrieval to academic corpora. Industry evidence must
therefore be requested explicitly: named companies, platforms, products,
pipeline stages, partnerships, and deployment scale **as reported in papers
or preprints**. Patent, company, and market corpora are intentionally
excluded. State this limitation in the final synthesis rather than implying
open-web industry coverage.

## Artifacts

Use one topic directory throughout:

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

`tmp_state.json` may hold both task and batch entries because entries are
keyed by task or batch ID. Do not submit the standard batch while the heavy
task is still live: collect the heavy report and run `enrich-check` first.

## Workflow

```text
- [ ] 1 Fast probe → research_init.md (repeat until the topic reads right)
- [ ] 2 Refine → research_idea.md
- [ ] 3 Heavy full-scope run → research_deep.md
- [ ] 4 Run enrich-check; identify dropped and thin facets
- [ ] 5 Build ideas.json; submit standard batch
- [ ] 6 Collect, retry, audit, and synthesize
```

### 1. Fast probe

Agree on `work/<topic-slug>/` with the user. Use one focused semantic query
with a dated recency window and explicit academic + industry evidence needs.
No search operators and no `--main-topic` on the baseline.

```bash
VALYU_CATEGORIES=research python \
  .cursor/skills/research-single-topic/scripts/research_runner.py run \
  --query "MAIN_TOPIC with 2024–2026 academic results and industry advances" \
  --output "work/<topic-slug>/research_init.md" \
  --mode fast --max-cost 1.00
```

Read the report. Repeat the fast probe if it chose the wrong sense, returned
a safety/regulatory survey, missed recent work, or lacks named technical
terms and evidence. Only promote a baseline that reads correctly.

### 2. Refine → `research_idea.md`

Write `work/<topic-slug>/research_idea.md` using this template:

```markdown
# Research Idea

**Main Topic:** [same topic as the baseline]
**Scope Terms:** [4–8 precise terms from the baseline]
**Coverage Facets:** [substantive baseline H2s to retain]
**Recency Window:** [explicit years]
**Deliberately Dropped:** [safety/regulatory/market facets, or "none"]
**Out of Scope:** [adjacent fields and de-emphasized subjects]
**Formulated Query:** [same whole topic, made precise]

### Refinements Over the Baseline Query
- [vague wording → field terminology]
- [thin or contested evidence to resolve]

### Scope Check
- Breadth: [all retained facets covered]
- Subject: [main subject unchanged]
- Boundary: [adjacent fields excluded]
- Emphasis: [recent academic + industry advances]
```

Go more precise, not narrower. The heavy query must retain the whole topic;
one-facet questions belong in the later batch.

### 3. Heavy full-scope research

Submit asynchronously with the unchanged parent topic:

```bash
VALYU_CATEGORIES=research python \
  .cursor/skills/research-single-topic/scripts/research_runner.py run \
  --query "FORMULATED_QUERY" \
  --output "work/<topic-slug>/research_deep.md" \
  --main-topic "MAIN_TOPIC" \
  --mode heavy --no-wait --max-cost 5.00
```

Tell the user the task ID. Collect it later:

```bash
python .cursor/skills/research-single-topic/scripts/research_runner.py status \
  --task-id "TASK_ID" \
  --output "work/<topic-slug>/research_deep.md"
```

The runner aborts before API spend if the refined query changes subject or
covers too little of the main topic. Fix the query instead of using
`--allow-drift`, unless the wording is genuinely equivalent.

### 4. Audit the heavy report

Run the free local audit:

```bash
python .cursor/skills/research-single-topic/scripts/research_runner.py enrich-check \
  --baseline "work/<topic-slug>/research_init.md" \
  --deep "work/<topic-slug>/research_deep.md"
```

Add one `--allow-drop "SUBSTRING"` for every deliberately dropped facet from
`research_idea.md`. Read the reports as well as the heading heuristic. Record:

- baseline facets not carried over;
- facets carried over without stronger data or sources;
- contradictions or vague claims still unresolved;
- new heavy sections that drift from the main topic.

These gaps drive the batch. Do not produce a generic second survey.

### 5. Build `ideas.json` and submit the standard batch

Use substantive H2s from `research_deep.md` as `anchor_headings`, plus the
eligible baseline H2 for any facet the heavy report dropped. Add focused
queries for dropped/thin baseline facets and for heavy sections needing
deeper evidence. Each query must be a strict subset of the main topic, name
its anchor, include the dated recency window, and preserve the academic +
industry emphasis.

```json
{
  "main_topic": "Same main topic as stages 1 and 2",
  "anchor_terms": ["distinctive phrase 1", "distinctive phrase 2"],
  "anchor_headings": ["1. Heavy report heading", "2. Dropped baseline heading"],
  "queries": [
    {
      "id": "Q01",
      "anchor": "1. Heavy report heading",
      "query": "Focused 2024–2026 drill-down with academic results and named industry evidence"
    }
  ]
}
```

Keep at most 12 non-overlapping queries. Reject catch-all anchors such as
Executive Summary, Conclusion, Sources, Applications, Future Directions,
Recent Developments, and Emerging.

```bash
VALYU_CATEGORIES=research python \
  .cursor/skills/research-multi-angle/scripts/research_runner.py batch \
  --queries-file "work/<topic-slug>/ideas.json" \
  --output-dir "work/<topic-slug>" \
  --name "Full Research: MAIN_TOPIC" \
  --mode standard --no-wait --max-cost 7.00
```

Tell the user the batch ID.

### 6. Collect, retry, audit, and synthesize

```bash
python .cursor/skills/research-multi-angle/scripts/research_runner.py status \
  --batch-id "BATCH_ID" --output-dir "work/<topic-slug>"
```

Retry only failed/cancelled tasks, preserving the research pin:

```bash
VALYU_CATEGORIES=research python \
  .cursor/skills/research-multi-angle/scripts/research_runner.py retry \
  --manifest "work/<topic-slug>/manifest.json" \
  --output-dir "work/<topic-slug>" \
  --mode standard --max-cost 2.00
```

Then run the free scope audit:

```bash
python .cursor/skills/research-multi-angle/scripts/research_runner.py scope-check \
  --manifest "work/<topic-slug>/manifest.json" \
  --queries-file "work/<topic-slug>/ideas.json"
```

Synthesize baseline → heavy → batch. Report the strongest recent advances,
academic evidence, industry signals available within research sources,
remaining disagreements, and any source-scope limitation. Summarize each
report by filepath and major finding.

Optional citation audit:

```bash
python .cursor/skills/research-verify/scripts/verify_references.py verify \
  --input "work/<topic-slug>/*.md" --max-cost 1.00
```

## Cost and practices

| Stage | Mode | Estimate | Recommended limit |
| --- | --- | ---: | ---: |
| Fast probe | `fast` | ~$0.10 each | `$1.00` |
| Full-scope report | `heavy` | ~$2.50 | `$5.00` |
| Up to 12 drill-downs | `standard` | up to ~$6.00 | `$7.00` |

- Expected worst case for one probe + heavy + 12 standard tasks: ~$8.60.
- Always use `--no-wait` for heavy and batch submissions.
- Never hardcode or print `VALYU_API_KEY`.
- Never start the batch before the heavy report and enrichment audit exist.
- Retry failures before the final synthesis.
