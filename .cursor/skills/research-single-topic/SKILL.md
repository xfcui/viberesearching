---
name: research-single-topic
description: >-
  Two-pass Valyu DeepResearch: cheap fast probes to de-risk the query, then one
  precision-refined heavy run that enriches the winning baseline — async polling,
  optional HITL, scope guardrails, enrichment audit, and cost limits. Use for
  deep research, fast-vs-heavy comparison, or a single high-quality dive on one
  topic. Not for multi-facet parallel batches (research-multi-angle) or
  enriching user-supplied content (research-enrich).
---

# Single-Topic Research

**Shape: cheap fast probes until the topic reads right, then exactly one heavy run that enriches the winning baseline.** Outputs under `work/deep/`.

Two ideas drive the whole workflow:

- **Fail cheap.** A misread topic costs $0.10 and ~5 min at `fast`, versus $2.50 and ~90 min at `heavy` — 25× the money and ~18× the wait to discover the query meant something else. So trial-and-error the query at `fast` and only promote a baseline you actually believe.
- **Heavy enriches, never replaces.** The heavy run re-asks the *same* topic with a far more precise description, and every baseline facet must come back stronger. A heavy report that answers one facet in depth while dropping the rest is a downgrade, whatever its page count.

**Not this skill:** many parallel facets → `research-multi-angle`. Enrich
supplied content → `research-enrich`. Citation audit → `research-verify`.
Quick cited lookup → the Valyu Answer/Search API directly (do not spend
DeepResearch on that).

## Default emphasis

Unless the request says otherwise, aim every query at **recent advances in academia and industry**:

| Prefer | De-emphasize |
|---|---|
| Results, mechanisms, and architectures from roughly the last three years | Regulatory frameworks, approval pathways, cross-agency harmonization |
| Named groups, labs, and papers — peer-reviewed or preprint | Safety, toxicology, and risk profiles as subjects in themselves |
| Industry pipelines, products, platforms, partnerships, deployment scale | Security and compliance posture |
| Benchmark numbers *and the delta* over the prior state of the art | Market-size forecasts and vendor landscapes |

De-emphasized material is still fair game where it **explains an advance** — the readout that gated a platform, the failure that redirected a design. It is out of scope as a subject in its own right, and it is never a substitute for technical evidence.

Express recency as a dated constraint inside the query (`2024–2026 results`), never by anchoring to a `Recent Developments` or `Emerging` heading. Those stay ineligible anchors: a catch-all heading licenses unlimited breadth no matter how current the material (`.cursor/rules/valyu-api.mdc` §10).

**Runner:** `.cursor/skills/research-single-topic/scripts/research_runner.py`

| Command | Purpose |
|---|---|
| `run` | Create task (`--main-topic`, `--no-wait`, `--hitl`, `--max-cost`, `--mode`) |
| `status` | Poll + download |
| `respond` | Reply to HITL checkpoint |
| `enrich-check` | Local audit of heavy vs baseline coverage (no API cost) |

Baseline is `fast` (~$0.10, ~5 min); the heavy run is `heavy` (~$2.50, ~90 min). Default `--max-cost` $3.00. `standard` and `max` remain valid CLI modes but are not part of this workflow.

Shared Valyu rules: `.cursor/rules/valyu-api.mdc` (§10 covers scope anchoring; deep uses the full-scope variant of the gate).

---

## Workflow

```
- [ ] 1 run --mode fast → work/deep/research_init.md   (repeat until the topic reads right)
- [ ] 2 Refine → work/deep/research_idea.md (same topic, precise scope)
- [ ] 3 run --mode heavy --main-topic --no-wait → work/deep/research_deep.md
- [ ] 4 status → enrich-check → synthesize fast vs heavy
- [ ] 5 (optional) research-verify / HITL if enabled
```

### 1. Baseline probe — cheap, and repeat it

Write a focused natural-language query (specific terminology, timeframe if useful). No `site:` / boolean operators. No `--main-topic` here — the baseline *is* the topic.

```bash
python .cursor/skills/research-single-topic/scripts/research_runner.py run \
  --query "MAIN_TOPIC" --output "work/deep/research_init.md" --mode fast
```

Then read it before spending anything else. Re-run `fast` with a corrected query — as many times as it takes — if any of these hold:

- **Wrong sense** of an ambiguous term (the field you meant is not the field that came back).
- **Wrong framing** — a market survey, regulatory overview, or safety review came back where the default emphasis wanted recent advances.
- **Stale** — the newest work cited is years old, or the report reads as a historical survey with no current state of the art.
- **Headings are not your facets** — the H2s do not resemble the breakdown you had in mind, which means heavy would organize itself the same wrong way.
- **Terminology feels generic** — no named mechanisms, platforms, metrics, groups, or products to harvest for step 2.

A second or third `fast` run is ~$0.10 and ~5 min each. Only promote a baseline you believe; the version you promote is the one heavy is contracted to enrich, so name it `work/deep/research_init.md` and keep rejected probes out of the way.

### 2. Refine the topic → `work/deep/research_idea.md`

Go **more precise, not narrower**. The heavy query keeps the baseline's full
topic and scope; what changes is how exactly that scope is described. Picking
one facet and drilling into it is `research-multi-angle`'s job, not this one —
a single heavy run spent on one facet throws away the rest of the topic.

The contract is enrichment: for every substantive baseline H2, heavy should return a counterpart that is deeper, better-sourced, or corrected. Nothing the baseline covered may vanish.

Mine the baseline for four things and fold them into the query:

1. **Terminology** — swap the opening query's generic nouns for the field's actual terms as the baseline uses them (its recurring named mechanisms, platforms, metrics, units).
2. **Coverage** — name the facets heavy must cover, taken from the baseline's substantive H2s, so it cannot collapse onto whichever one has the most literature. Facets sitting outside the default emphasis — regulatory, safety, market sizing — may be compressed to a line or dropped outright; record that under **Deliberately Dropped** so the step-4 audit does not read it as a regression.
3. **Boundaries** — state what is out of scope. Heavy has budget to wander into adjacent fields that merely *explain* the topic rather than being it — the upstream basic science, the neighboring discipline, general practice in the domain. Start from the default de-emphasis list and add whatever the baseline shows this topic drifts toward. The query is the only place to forbid that.
4. **Evidence bar** — what counts as an answer: quantitative values with units, named studies and groups, primary or peer-reviewed sources, and an explicit recency window (name the years). For industry claims, require the concrete signal — product, pipeline stage, partnership, funding, deployment scale — not a market projection. Also list any baseline claim that was vague, unnamed, or contested and now needs resolving.

Query craft: one topic per query, so this is a precise topic statement, not a survey essay. Keep it under ~380 chars. Phrase it so the main topic's own wording appears inside it — then the runner's anchor clause is a no-op and the whole budget goes to the semantic payload.

```markdown
# Deep Research Idea

**Main Topic:** [same as baseline — unchanged]
**Scope Terms:** [4–8 precise phrases harvested from the baseline]
**Coverage Facets:** [baseline H2s the heavy report must cover]
**Recency Window:** [years that count as current for this field]
**Deliberately Dropped:** [baseline facets outside the emphasis, or "none"]
**Out of Scope:** [adjacent fields heavy must not drift into]
**Formulated Query:** [same topic, precisely specified]

### Refinements Over the Baseline Query
- [Vague wording → precise terminology, with the baseline term used]
- [Facet the baseline covered too thinly, now named explicitly]
- [Vague / unnamed / contested baseline claim the heavy run must resolve]

### Scope Check
- Breadth test: [covers every coverage facet — not narrowed to one, not extended past the topic]
- Subject test: [subject is unchanged from the main topic]
- Boundary test: [out-of-scope list names the adjacent fields heavy could wander into]
- Emphasis test: [aimed at recent academic + industry advances; anything dropped is listed above]
```

### 3. Heavy research

Pass `--main-topic` so the run is gated against the baseline topic, and prefer `--no-wait` (heavy often ~90 min):

```bash
python .cursor/skills/research-single-topic/scripts/research_runner.py run \
  --query "FORMULATED_QUERY" --output "work/deep/research_deep.md" \
  --main-topic "MAIN_TOPIC" --mode heavy --no-wait --max-cost 5.00
```

The runner gates the query on **full scope coverage** before spending anything: it aborts if the query shares no distinctive terminology with the main topic (wrong subject) *or* if it covers less than half of it (narrowed to a facet). Fix the query rather than overriding. `--allow-drift` downgrades both to warnings — use it only when the refined wording is genuinely equivalent to the topic, or when you deliberately want a narrow one-facet run.

Tell the user the Task ID. Poll:

```bash
python .cursor/skills/research-single-topic/scripts/research_runner.py status \
  --task-id "TASK_ID" --output "work/deep/research_deep.md"
```

On success the runner removes `work/deep/tmp_*.json` automatically.

### 4. Synthesis

Start with the free local audit — it matches heavy's H2s against the baseline's on shared terminology, so reworded headings still count:

```bash
python .cursor/skills/research-single-topic/scripts/research_runner.py enrich-check \
  --baseline "work/deep/research_init.md" --deep "work/deep/research_deep.md" \
  --allow-drop "Regulatory" --allow-drop "Safety"
```

Pass one `--allow-drop SUBSTRING` per entry in the note's **Deliberately Dropped** list; those facets are reported separately instead of as failures. **Enriched** is the contract being met. **Not carried over** is a genuine regression. **New in heavy, off topic** is drift — sections with no baseline home and none of the topic's terminology. Both problem lists are heading-level heuristics, so read the flagged sections before reporting them.

Then judge what the audit cannot:

- **Depth per facet** — did each carried-over facet actually gain (quantitative values, named studies, resolved contradictions), or is it the same claims restated at greater length?
- **Recency** — is the newest cited work inside the declared window, and does the report say what changed rather than just what exists?
- **Boundaries** — anything on the ideation note's out-of-scope list, or sections where an adjacent field *explaining* the topic has displaced the topic itself.
- **Citation integrity** — claims carrying specific primary data (named
  cohorts, trial arms, measured values) attributed to sources that cannot
  contain them: encyclopedia or wiki pages, aggregators, or a numbered source
  whose title does not match the claim. Spot-check the `## Sources` block
  against the densest claims, then offer `research-verify`.

Report the fast-vs-heavy cost-benefit honestly. If heavy dropped facets and drifted, say so — the remedy is a re-run from step 2 with the missing facets named, not a rewrite of the summary.

### 5. Optional reference verification

```bash
python .cursor/skills/research-verify/scripts/verify_references.py verify \
  --input "work/deep/*.md" --max-cost 1.0
# then if needed:
python .cursor/skills/research-verify/scripts/verify_references.py retry \
  --input "work/deep/*.md"
```

---

## HITL (optional)

```bash
python .cursor/skills/research-single-topic/scripts/research_runner.py run \
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
python .cursor/skills/research-single-topic/scripts/research_runner.py respond \
  --task-id "TASK_ID" --response-file "work/deep/tmp_checkpoint_response.json"
```

---

## Cost & practices

| Stage | Mode | Est. | Duration | `--max-cost` |
|---|---|---|---|---|
| Baseline probe (repeatable) | fast | $0.10 | ~5 min | $1 |
| Heavy run | heavy | $2.50 | ~90 min | $5 |

- Spend `fast` freely to de-risk the query; spend `heavy` once. Three probes plus one heavy still costs less than two heavies.
- Default emphasis is recent academic + industry advances (see above). Regulatory, safety, security, and market framing only where they explain an advance.
- Never hardcode/log `VALYU_API_KEY`. Always pass `--max-cost`.
- `--no-wait` for the heavy run; state in `work/deep/tmp_state.json`, auto-removed on success.
- Always pass `--main-topic` on the heavy run — that is what enables the full-scope gate. Only the baseline runs unanchored.
- Never skip step 2, and never promote a baseline you have not read. Re-running the opening query at `heavy` wastes ~25× the baseline's cost on the same under-specified brief.
- `enrich-check` is free and local — run it on every heavy report before writing the synthesis.
- Source scope today: `[valyu] categories` / `VALYU_CATEGORIES` → first token → `search.category`. Omit for all sources.
- The default emphasis spans academia **and** industry, so `categories = research` will starve the industry half — it restricts retrieval to academic corpora, which is also how a report ends up citing company and agency facts through review articles. Prefer all sources; `VALYU_CATEGORIES= python …` clears it for one run without editing `.env`.
- Quick lookups → Valyu Answer/Search, not this skill (see `.cursor/rules/valyu-api.mdc` §0).
