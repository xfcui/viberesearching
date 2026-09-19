---
name: enrich-research
description: >-
  Fast-mode Valyu batch research to enrich talk storytelling and visuals from
  user-supplied source content (an idea note plus a slide outline, whatever
  they are named). Writes work/enrich/* (brief, ideas.json, reports). Use for
  enrich-research, storytelling/visual enrichment, or craft research on an
  existing talk. Not for generic topic exploration (batch-research) or domain
  deep-dives (deep-research).
---

# Enrich Research

**Shape: no baseline + fast researches bounded only by `--max-cost`.** Enrich an existing talk spine with **storytelling** and **visual** craft. Reuse `.cursor/skills/batch-research/scripts/research_runner.py` — do not invent another client.

**Not this skill:** generic topic exploration → `batch-research`. Domain deep-dives → `deep-research`.

## Inputs

**Source content is whatever the user provides.** Never assume filenames, never glob the workspace, never guess. Accept `@` mentions, any path, or text pasted into chat. If a role below is missing, **ask once** and wait.

| Role | What it carries |
|---|---|
| Idea / intent | Title, audience, job, hook, arc, visual system |
| Structure / outline | Slides with Visual / Speech (or equivalent) |

Optional extras if the user offers them: principles notes, style plates, brand references.

## Output

**All artifacts → `work/enrich/`** (default; override with `--output-dir`):

| File | Who writes |
|---|---|
| `brief.md` | Agent — design note, resolved sources, scope contract |
| `ideas.json` | Agent — anchored batch payload |
| `researchNN_*.md`, `manifest.json` | Runner |
| `tmp_state.json` | Runner — async state, auto-removed on success |

## Hard rules

1. **Mode:** always `--mode fast`.
2. **Budget:** `--max-cost` is the only ceiling. Aim for `query_count ≈ ⌊max_cost / 0.10⌋` minus a small buffer, and pick from real craft gaps — never pad to fill the budget.
3. **No baseline.** Batch-only, always. A baseline here drifts into a domain survey instead of talk craft.
4. **Scope:** techniques usable on this deck (patterns, anti-patterns, speech/visual moves). Not literature tours of the talk's domain.
5. **Preserve** the idea's palette/motifs as constraints. Do not rewrite the outline unless asked.
6. **Secrets:** never read `.env` into chat; runner loads `VALYU_API_KEY`.
7. **Categories:** `[valyu] categories=research` (or similar) biases enrich toward academic corpora—wrong for storytelling/visuals. Prefer unset/all sources for enrich runs. See `.cursor/rules/valyu-api.mdc`.

## Workflow

```
- [ ] 1 Resolve source content + scope contract
- [ ] 2 Write brief.md
- [ ] 3 Write ideas.json
- [ ] 4 Submit batch --no-wait (or status if resuming)
- [ ] 5 status → retry failures → summarize takeaways
```

### 1. Resolve

Read whatever the user supplied and pull out: the talk's job, arc, motifs, and thin spots (weak Visual/Speech, repeated systems that need rules). From that content derive the scope contract:

- `main_topic` — the **craft** topic, e.g. "storytelling and visual craft for a talk on X". Not the talk's subject matter.
- `anchor_terms` — distinctive craft phrases plus the deck's own motifs.
- `anchor_headings` — headings taken from the user's outline (slide titles or sections). If the source is unstructured prose, leave this out; `main_topic` and `anchor_terms` still gate the queries.

If `work/enrich/tmp_state.json` already has a live batch id, **status that first** — do not double-submit.

### 2. `brief.md`

Short design note: talk job, why research, visual constraints, the resolved source list (so the run stays auditable without fixed filenames), the scope contract, chosen `query_count`, and the track split. No essay.

### 3. `ideas.json`

Derive queries from **this** outline's gaps, not a generic template.

| Track | IDs | Use for |
|---|---|---|
| storytelling | `S##` | Hooks, sticky Q, shifts, CTA, mentor framing, anti-patterns |
| visual | `V##` | Motif system, curtain/content rhythm, pipeline/ladder/funnel, palette, clutter |
| synthesis | `X##` | 1–2 speech×visual co-design checklists if budget allows |

Rough split: ~half S / half V / ≤2 X.

```json
{
  "main_topic": "storytelling and visual craft for THIS talk",
  "anchor_terms": ["talk craft phrase", "deck motif"],
  "anchor_headings": ["Outline section", "Outline section"],
  "context": {
    "title": "...",
    "speaker_role": "...",
    "arc": "...",
    "visual_system": "..."
  },
  "queries": [
    {"id": "S01", "track": "storytelling", "anchor": "Outline section", "query": "..."}
  ]
}
```

The runner sends only `query` strings, anchored to `main_topic`; `id`, `track`, and `anchor` are kept for local maps and the manifest. Each query: specific, deck-actionable, in-scope; prefer under ~250 chars; no `site:` / boolean operators or domain lit-review phrasing. One query may cover a cluster of related slides.

**Domain-drift test:** a query is drift if it researches the talk's *subject matter* rather than a technique you could apply to the deck. Combine with the three-test gate in `.cursor/rules/valyu-api.mdc` §10.

**Litmus:** merged reports deepen craft for the existing spine, not a new domain.

### 4. Submit

```bash
python .cursor/skills/batch-research/scripts/research_runner.py batch \
  --queries-file "work/enrich/ideas.json" \
  --output-dir "work/enrich" \
  --name "<short title>" \
  --mode fast \
  --max-queries 0 \
  --no-wait \
  --max-cost <chosen budget>
```

`--max-queries 0` opts out of batch-research's 12-query cap, leaving `--max-cost` as the only ceiling. Tell the user the Batch ID; the runner records it in `work/enrich/tmp_state.json`.

Sync wait only if ≤5 queries and the user wants to stay in-session.

### 5. Collect + summarize

```bash
python .cursor/skills/batch-research/scripts/research_runner.py status \
  --batch-id "BATCH_ID" --output-dir "work/enrich"
```

On failures:

```bash
python .cursor/skills/batch-research/scripts/research_runner.py retry \
  --manifest "work/enrich/manifest.json" \
  --output-dir "work/enrich" --mode fast --max-cost 2.00
```

Temp state is cleared automatically once every task succeeds, and kept while any task still needs a retry.

Summarize: path × track × 1–2 usable speech or visual takeaways. Optional OpenAlex audit only if asked:

```bash
python .cursor/skills/verify-references/scripts/verify_references.py verify \
  --input "work/enrich/*.md" --max-cost 1.0
```
