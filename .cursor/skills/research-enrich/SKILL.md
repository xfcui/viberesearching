---
name: research-enrich
description: >-
  Fast-mode Valyu batch research that enriches any user-supplied content with
  current evidence, examples, context, counterpoints, and useful source
  material. Accepts notes, drafts, articles, reports, outlines, presentations,
  or pasted text and writes work/enrich/*. Use when the user wants to
  strengthen existing content without replacing its purpose or structure.
  Not for open-ended topic exploration or a standalone deep dive.
---

# Research Enrichment

**Shape: user content + no baseline + focused fast researches bounded by
`--max-cost`.** Enrich what already exists. Reuse
`.cursor/skills/research-multi-angle/scripts/research_runner.py`; do not
invent another client.

**Not this skill:** open-ended multi-facet topic exploration →
`research-multi-angle`. One full-scope heavy dive →
`research-single-topic`. Complete fast → heavy → batch research →
`research-comprehensive`.

## Inputs

**Source content is exactly what the user provides.** Accept `@` mentions,
any path, or text pasted into chat. Never assume filenames, glob the
workspace, or guess at missing source material. One source is enough. If no
content was supplied, ask once and wait.

Examples include:

- notes, briefs, proposals, and plans;
- article, report, paper, or documentation drafts;
- scripts, outlines, curricula, and presentations;
- product, strategy, or design documents;
- unstructured pasted text.

Optional context: audience, desired outcome, publication format, constraints,
and the sections the user most wants strengthened.

## Output

**All artifacts → `work/enrich/`** unless the user requests another output
directory:

| File | Who writes |
| --- | --- |
| `brief.md` | Agent — resolved inputs, content intent, gaps, scope contract |
| `ideas.json` | Agent — anchored enrichment queries |
| `researchNN_*.md`, `manifest.json` | Runner |
| `tmp_state.json` | Runner — async state, auto-removed on success |

Research reports provide enrichment material. Do not rewrite the user's
source unless they separately ask for integration or editing.

## Hard rules

1. **Mode:** always `--mode fast`.
2. **Budget:** `--max-cost` is the ceiling. Choose queries from real content
   gaps; never pad to spend the budget.
3. **No baseline:** batch only. The supplied content already provides the
   spine and scope.
4. **Preserve intent:** research strengthens the content's purpose, audience,
   voice, claims, and structure; it does not silently replace them.
5. **Anchor every query:** each query must trace to a supplied heading,
   passage, claim, or explicit content goal.
6. **No generic survey:** research only material that can improve the given
   content.
7. **Secrets:** never read `.env` into chat; the runner loads
   `VALYU_API_KEY`.
8. **Categories:** prefer unset/all sources unless the user explicitly wants
   one corpus. `categories = research` can miss current products, companies,
   examples, and public context. Use `VALYU_CATEGORIES=` to clear it for this
   run.

## Workflow

```text
- [ ] 1 Resolve supplied content, intent, and enrichment gaps
- [ ] 2 Write brief.md
- [ ] 3 Write ideas.json
- [ ] 4 Submit fast batch --no-wait (or status an existing batch)
- [ ] 5 Collect, retry failures, and map findings back to the content
```

### 1. Resolve the content

Read only the user-supplied sources. Identify:

- the content's purpose, audience, and existing structure;
- claims that need evidence or updating;
- sections that need examples, comparisons, mechanisms, or quantitative data;
- missing context, counterpoints, implications, or practical details;
- visual or storytelling opportunities only when the format benefits from
  them;
- explicit boundaries: what must remain unchanged or out of scope.

Derive a scope contract:

- `main_topic` — "research enrichment for [specific supplied content]";
- `anchor_terms` — distinctive subject terms plus the content's intended use;
- `anchor_headings` — actual headings or section labels from the content. For
  unstructured text, create stable short labels tied to quoted passages or
  paragraph purposes.

If `work/enrich/tmp_state.json` contains a live batch ID, status it before
submitting another batch.

### 2. Write `brief.md`

Keep it short:

- resolved source list;
- purpose, audience, and format;
- what is already strong;
- concrete enrichment gaps;
- boundaries and preserve-as-is constraints;
- scope contract;
- chosen query count, budget, and track split.

### 3. Write `ideas.json`

Choose only tracks that match actual gaps:

| Track | IDs | Use for |
| --- | --- | --- |
| evidence | `E##` | Verify/update claims, primary sources, quantitative data |
| examples | `X##` | Cases, implementations, analogies, concrete illustrations |
| context | `C##` | Mechanisms, history, comparisons, implications |
| counterpoint | `Q##` | Limitations, competing evidence, credible objections |
| visual | `V##` | Diagrams, imagery, demonstrations, only when useful |

```json
{
  "main_topic": "research enrichment for THIS supplied content",
  "anchor_terms": ["distinctive subject phrase", "content purpose"],
  "anchor_headings": ["Actual section", "Claim or passage label"],
  "context": {
    "content_type": "...",
    "audience": "...",
    "purpose": "...",
    "preserve": ["..."]
  },
  "queries": [
    {
      "id": "E01",
      "track": "evidence",
      "anchor": "Actual section",
      "query": "Focused research question that directly strengthens this section"
    }
  ]
}
```

The runner sends only each `query`, anchored to `main_topic`; the remaining
fields keep the local mapping auditable. Prefer queries under ~250 characters.
Do not use `site:`, Boolean operators, or unrelated literature-review asks.

**Drift test:** if a finding cannot be mapped to a specific passage, heading,
claim, or content goal, the query is too broad.

### 4. Submit

Clear category scoping so enrichment can use the most suitable academic,
industry, news, and public sources:

```bash
VALYU_CATEGORIES= python \
  .cursor/skills/research-multi-angle/scripts/research_runner.py batch \
  --queries-file "work/enrich/ideas.json" \
  --output-dir "work/enrich" \
  --name "Research enrichment: <short source title>" \
  --mode fast \
  --max-queries 0 \
  --no-wait \
  --max-cost <chosen budget>
```

`--max-queries 0` removes the multi-angle skill's 12-query cap;
`--max-cost` remains the hard ceiling. Tell the user the batch ID. Synchronous
waiting is acceptable only for five or fewer queries when the user wants to
stay in session.

### 5. Collect and map findings

```bash
python .cursor/skills/research-multi-angle/scripts/research_runner.py status \
  --batch-id "BATCH_ID" --output-dir "work/enrich"
```

Retry failures:

```bash
VALYU_CATEGORIES= python \
  .cursor/skills/research-multi-angle/scripts/research_runner.py retry \
  --manifest "work/enrich/manifest.json" \
  --output-dir "work/enrich" --mode fast --max-cost 2.00
```

Summarize each report as:

- report path and track;
- source heading, passage, or goal it enriches;
- 1–3 usable findings;
- whether the finding supports, updates, complicates, or contradicts the
  current content;
- suggested integration point, without rewriting unless asked.

Optional citation audit:

```bash
python .cursor/skills/research-verify/scripts/verify_references.py verify \
  --input "work/enrich/*.md" --max-cost 1.0
```
