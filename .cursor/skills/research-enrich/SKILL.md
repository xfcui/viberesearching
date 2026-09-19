---
name: research-enrich
description: >-
  Fast Valyu fan-out that strengthens any user-supplied content with current
  evidence, examples, context, counterpoints, and source material. Accepts
  notes, drafts, articles, reports, outlines, presentations, or pasted text.
  Use when existing content is the spine and should be preserved. Not for an
  open-ended topic baseline or a heavy standalone report.
---

# Research Enrichment

**Stages: supplied content → fast fan-out.**

Follow `.cursor/rules/valyu-api.mdc` for shared fan-out, source, cost, async,
scope, and recovery policy. This workflow has no fast topic baseline and no
heavy stage; the supplied content is already the scope.

Use `research-multi-angle` when the goal is a new topic survey rather than
strengthening existing content.

## Inputs and outputs

Use exactly the content the user provides: any path, `@` mention, or pasted
text. Never glob, guess filenames, or silently choose extra sources. If no
content was supplied, ask once.

```text
work/enrich/
├── brief.md
├── ideas.json
├── researchNN_*.md
├── manifest.json
└── tmp_state.json
```

Research reports form an enrichment pack. Do not rewrite the source unless
the user separately requests integration.

## Workflow

```text
- [ ] 1 Resolve supplied content, intent, primary spine, and gaps
- [ ] 2 Write work/enrich/brief.md
- [ ] 3 Write anchored tracks → work/enrich/ideas.json
- [ ] 4 Fast fan-out
- [ ] 5 Collect, retry, and map findings back to passages
```

Check `work/enrich/tmp_state.json` first and resume matching live work.

### 1. Resolve and brief

Identify:

- purpose, audience, format, and primary content spine;
- claims needing evidence or updating;
- gaps needing examples, mechanisms, comparisons, counterpoints, or data;
- visual/storytelling opportunities only when the format benefits;
- passages, voice, structure, and constraints to preserve.

Write `brief.md` with resolved inputs, content intent, gaps, boundaries,
stable heading/passage labels, chosen query count, and budget.

### 2. Ideas

Choose only tracks justified by actual gaps:

| Track | IDs | Purpose |
| --- | --- | --- |
| evidence | `E##` | Claims, primary sources, quantitative data |
| examples | `X##` | Cases, implementations, concrete illustrations |
| context | `C##` | Mechanisms, comparisons, implications |
| counterpoint | `Q##` | Limitations and credible objections |
| visual | `V##` | Diagrams or demonstrations when useful |

```json
{
  "main_topic": "Actual subject of the supplied content",
  "anchor_terms": ["distinctive subject phrase", "content purpose"],
  "anchor_headings": ["Actual heading", "Stable passage label"],
  "queries": [
    {
      "id": "E01",
      "track": "evidence",
      "anchor": "Actual heading",
      "query": "Focused question that directly strengthens this passage"
    }
  ]
}
```

If a result cannot map to a declared passage, heading, claim, or content goal,
the query is too broad.

### 3. Fast fan-out

Clear category scoping unless the user requested a corpus:

```bash
VALYU_CATEGORIES= python \
  .cursor/skills/research-multi-angle/scripts/research_runner.py batch \
  --queries-file "work/enrich/ideas.json" \
  --output-dir "work/enrich" \
  --name "Research Enrichment: <source title>" \
  --mode fast --max-queries 0 --no-wait \
  --max-cost <chosen-budget>
```

Query count is budget-limited, not capped at 12. Do not pad the batch.

Collect with `status`. Retry failed/cancelled entries in `fast` mode using
`failed_count × $0.10` plus a small buffer and the same all-source override.

## Handoff

For every manifest entry, report:

- report path, track, and source anchor;
- 1–3 usable findings;
- whether each supports, updates, complicates, or contradicts the content;
- suggested integration point without rewriting the source.

`research-verify` can audit scholarly citations. OpenAlex cannot validate
ordinary company pages, news, blogs, or other non-scholarly sources.
