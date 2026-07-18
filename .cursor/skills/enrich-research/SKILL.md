---
name: enrich-research
description: >-
  Fast-mode Valyu batch research to enrich talk storytelling and visuals from an
  idea note plus slide outline. Writes work/research/* (brief, ideas.json, reports).
  Use for enrich-research, storytelling/visual enrichment, or craft research from
  idea.md + outline_*.md (filenames may differ). Not for generic topic exploration
  (batch-research) or domain deep-dives (deep-research).
---

# Enrich Research

Enrich an existing talk spine with **storytelling** and **visual** craft via Valyu DeepResearch **`fast`** batch. Reuse `.cursor/skills/batch-research/scripts/research_runner.py` — do not invent another client.

**Not this skill:** generic topic exploration → `batch-research`. Domain deep-dives → `deep-research`.

## Inputs / output

| Role | Typical path | Extract |
|---|---|---|
| Idea | `work/idea.md` | Title, audience, job, hook, arc, visual system |
| Outline | `work/outline_*.md` | Slides with Visual / Speech (or equivalent) |

Paths may differ — use `@` mentions. Ask once if missing. Optional: `work/principles.md`, style plates.

**All artifacts → `work/research/`** (create if needed):

| File | Who writes |
|---|---|
| `brief.md` | Agent — design note + `content_page_count` |
| `ideas.json` | Agent — batch payload |
| `batch_state.json` | Agent — ids, tracks, poll command |
| `researchNN_*.md`, `manifest.json`, `active_batches.json` | Runner |
| `00_research_init.md` | Runner only if user asks for a baseline |

## Hard rules

1. **Mode:** always `--mode fast`.
2. **Budget:** `total_researches ≤ content_page_count`. Prefer fewer; never pad.
3. **Default path:** batch-only. Skip single/baseline unless the user asks — baselines often drift into domain surveys instead of talk craft.
4. **Scope:** techniques usable on this deck (patterns, anti-patterns, speech/visual moves). Not literature tours of the talk’s domain.
5. **Preserve** the idea’s palette/motifs as constraints. Do not rewrite the outline unless asked.
6. **Secrets:** never read `.env` into chat; runner loads `VALYU_API_KEY`.
7. **Categories:** `[valyu] categories=research` (or similar) often biases enrich toward academic corpora—wrong for storytelling/visuals. Prefer unset/all sources for enrich runs. See `.cursor/rules/valyu-api.mdc`.

### Content-page count

| Include | Exclude |
|---|---|
| Light content slides (argument, diagram, CTA, pedagogy) | Dark curtain / roadmap / cover / intermission / ending |

Count `## Slide N` (or equivalent) by Visual note. Ambiguous → include. Record in `brief.md` and `batch_state.json`.

`total_researches` = `(baseline ? 1 : 0) + len(queries)`.

| | Value |
|---|---|
| **Soft target** | `⌊content_page_count / 2⌋` |
| **Hard limit** | `content_page_count` |

Aim for the soft target; go higher only for distinct craft gaps, never above the hard limit. `--max-cost` ≈ `total_researches × 0.10 + 0.50`.

## Workflow

```
- [ ] 1 Resolve inputs + content_page_count
- [ ] 2 Write brief.md
- [ ] 3 Write ideas.json (≤ budget)
- [ ] 4 Submit batch --no-wait (or status if resuming)
- [ ] 5 status → retry failures → summarize takeaways
```

### 1. Resolve

Read idea + outline for job, arc, motifs, thin spots (weak Visual/Speech, repeated systems that need rules). If `work/research/batch_state.json` already has a live batch id, **status that first** — do not double-submit.

### 2. `brief.md`

Short design note: talk job, why research, visual constraints, `content_page_count`, chosen `query_count`, track split. No essay.

### 3. `ideas.json`

Derive queries from **this** outline’s gaps, not a generic template.

| Track | IDs | Use for |
|---|---|---|
| storytelling | `S##` | Hooks, sticky Q, shifts, CTA, mentor framing, anti-patterns |
| visual | `V##` | Motif system, curtain/content rhythm, pipeline/ladder/funnel, palette, clutter |
| synthesis | `X##` | 1–2 speech×visual co-design checklists if budget allows |

Rough split: ~half S / half V / ≤2 X.

```json
{
  "main_topic": "<enrich storytelling + visuals for THIS talk>",
  "context": {
    "title": "...",
    "speaker_role": "...",
    "arc": "...",
    "visual_system": "..."
  },
  "queries": [
    {"id": "S01", "track": "storytelling", "query": "..."}
  ]
}
```

Runner sends only `query` strings. Keep `id`/`track` for local maps. Each query: specific, deck-actionable, in-scope; prefer under ~400 chars; no `site:` / boolean operators or domain lit-review phrasing. One query may cover a cluster of related slides.

**Litmus:** merged reports deepen craft for the existing spine, not a new domain.

### 4. Submit

```bash
python .cursor/skills/batch-research/scripts/research_runner.py batch \
  --queries-file "work/research/ideas.json" \
  --output-dir "work/research" \
  --name "<short title>" \
  --mode fast \
  --no-wait \
  --max-cost <total_researches * 0.10 + 0.50>
```

Write `batch_state.json` (`content_page_count`, `query_count`, `batch_id`, track→ids, poll command). Tell the user the Batch ID.

Sync wait only if ≤5 queries and the user wants to stay in-session.

**Baseline (opt-in only):**

```bash
python .cursor/skills/batch-research/scripts/research_runner.py single \
  --query "<main_topic>" \
  --output "work/research/00_research_init.md" \
  --mode fast --no-wait --max-cost 0.50
```

Counts against the cap; shrink the batch accordingly.

### 5. Collect + summarize

```bash
python .cursor/skills/batch-research/scripts/research_runner.py status \
  --batch-id "BATCH_ID" --output-dir "work/research"
```

On failures:

```bash
python .cursor/skills/batch-research/scripts/research_runner.py retry \
  --manifest "work/research/manifest.json" \
  --output-dir "work/research" --mode fast --max-cost 2.00
```

Summarize: path × track × 1–2 usable speech or visual takeaways. Optional OpenAlex audit only if asked:

```bash
python .cursor/skills/verify-references/scripts/verify_references.py verify \
  --input "work/research/*.md" --max-cost 1.0
```
