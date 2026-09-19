# VibeResearching ✨

**Turn a topic into cited research reports — baselines, deep dives, and parallel facets — without babysitting the API.**

Cursor skills + Valyu DeepResearch runners handle the boring parts: async polling, retries, cost guardrails, and optional OpenAlex citation audits.

## Why VibeResearching? 🚀

- **Go deeper fast** — Cheap fast baselines to de-risk the topic, then one thorough heavy run *or* parallel facet batches
- **Cover depth and breadth** — Chain fast → heavy → standard batch in one topic directory when you need the complete path
- **Stay on topic** — Every follow-up carries its parent topic, and off-topic queries are rejected before you pay for them
- **Check your own work** — Free local audits catch topic drift and heavy runs that dropped what the baseline covered
- **Stay in budget** — `--max-cost` aborts before overspend
- **Recover gracefully** — Async submit/poll, batch retry, persistent OpenAlex cache
- **Content enrichment** — Add current evidence, examples, context, and
  counterpoints to any supplied content

## Pick a path

| You want… | Use | Shape | Outputs |
|-----------|-----|-------|---------|
| One topic with maximum depth and breadth | `research-comprehensive` | 1 fast + 1 heavy + ≤12 standard | `work/<topic-slug>/*` |
| One topic, done thoroughly | `research-single-topic` | 1 fast + 1 heavy | `work/deep/research_init.md` → `work/deep/research_deep.md` |
| Many facets of one topic, in parallel | `research-multi-angle` | 1 fast + ≤12 standard | `work/batch/ideas.json` + `work/batch/researchNN_*.md` |
| Strengthen any supplied content with evidence and context | `research-enrich` | fast, capped only by cost | `work/enrich/*` |
| Citation check after any of the above | `research-verify` | — | `{report}.json` sidecars (reports unchanged) |

In Cursor, invoke the matching skill (`research-comprehensive`,
`research-single-topic`, `research-multi-angle`, `research-enrich`,
`research-verify`). Or call the runners below directly.

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env   # add your Valyu key (+ optional OpenAlex)
```

## First run

A fast baseline is the cheapest way to see the pipeline:

```bash
python .cursor/skills/research-single-topic/scripts/research_runner.py run \
  --query "YOUR_TOPIC" --output work/deep/research_init.md --mode fast
```

Open `work/deep/research_init.md`. If the topic came back as something you
didn't mean, fix the query and re-run — that's $0.10 and ~5 minutes, versus
$2.50 and ~90 minutes to find out at `heavy`. Once the baseline reads right,
it tells you the field's real terminology and where the evidence is thin.
From there: run both heavy and a standard fan-out
(`research-comprehensive`), re-ask the same topic at heavy
(`research-single-topic`), fan out facets (`research-multi-angle`), or enrich
supplied content (`research-enrich`).

## Usage Examples

```bash
# Comprehensive: one topic directory, research sources pinned throughout
VALYU_CATEGORIES=research python \
  .cursor/skills/research-single-topic/scripts/research_runner.py run \
  --query "YOUR_TOPIC with 2024–2026 academic results and industry advances" \
  --output work/YOUR_TOPIC_SLUG/research_init.md --mode fast --max-cost 1.00
VALYU_CATEGORIES=research python \
  .cursor/skills/research-single-topic/scripts/research_runner.py run \
  --query "REFINED_FULL_SCOPE_QUERY" \
  --output work/YOUR_TOPIC_SLUG/research_deep.md \
  --main-topic "YOUR_TOPIC" --mode heavy --no-wait --max-cost 5.00
python .cursor/skills/research-single-topic/scripts/research_runner.py status \
  --task-id "TASK_ID" --output work/YOUR_TOPIC_SLUG/research_deep.md
python .cursor/skills/research-single-topic/scripts/research_runner.py enrich-check \
  --baseline work/YOUR_TOPIC_SLUG/research_init.md \
  --deep work/YOUR_TOPIC_SLUG/research_deep.md
# After the heavy audit, write anchored gaps to ideas.json, then fan out
VALYU_CATEGORIES=research python \
  .cursor/skills/research-multi-angle/scripts/research_runner.py batch \
  --queries-file work/YOUR_TOPIC_SLUG/ideas.json \
  --output-dir work/YOUR_TOPIC_SLUG \
  --name "Full Research: YOUR_TOPIC" \
  --mode standard --no-wait --max-cost 7.00

# Single-topic: same topic at heavy, precisely specified + poll
python .cursor/skills/research-single-topic/scripts/research_runner.py run \
  --query "REFINED_QUERY" --output work/deep/research_deep.md \
  --main-topic "YOUR_TOPIC" --mode heavy --no-wait --max-cost 5.00
python .cursor/skills/research-single-topic/scripts/research_runner.py status \
  --task-id "TASK_ID" --output work/deep/research_deep.md

# Single-topic: did heavy enrich the baseline? (free, local)
python .cursor/skills/research-single-topic/scripts/research_runner.py enrich-check \
  --baseline work/deep/research_init.md --deep work/deep/research_deep.md

# Single-topic: HITL checkpoint reply
python .cursor/skills/research-single-topic/scripts/research_runner.py respond \
  --task-id "TASK_ID" --response-file work/deep/tmp_checkpoint_response.json

# Multi-angle: baseline → ideas → parallel facets (≤12 standard by default)
python .cursor/skills/research-multi-angle/scripts/research_runner.py single \
  --query "YOUR_TOPIC" --output work/batch/research_init.md --mode fast
python .cursor/skills/research-multi-angle/scripts/research_runner.py batch \
  --queries-file work/batch/ideas.json --output-dir work/batch \
  --mode standard --no-wait --max-cost 7.00

# Multi-angle: status + retry failed tasks
python .cursor/skills/research-multi-angle/scripts/research_runner.py status \
  --batch-id "BATCH_ID" --output-dir work/batch
python .cursor/skills/research-multi-angle/scripts/research_runner.py retry \
  --manifest work/batch/manifest.json --output-dir work/batch --mode standard --max-cost 2.00

# Multi-angle: free local drift audit of finished reports
python .cursor/skills/research-multi-angle/scripts/research_runner.py scope-check \
  --manifest work/batch/manifest.json --queries-file work/batch/ideas.json

# Enrich: strengthen supplied content (agent skill writes ideas.json first)
VALYU_CATEGORIES= python \
  .cursor/skills/research-multi-angle/scripts/research_runner.py batch \
  --queries-file work/enrich/ideas.json --output-dir work/enrich \
  --name "Content enrichment" --mode fast --max-queries 0 --no-wait --max-cost 2.00

# Verify: audit ## Sources via OpenAlex (never rewrites reports)
python .cursor/skills/research-verify/scripts/verify_references.py verify \
  --input "work/deep/*.md" --max-cost 1.0
python .cursor/skills/research-verify/scripts/verify_references.py retry \
  --input "work/deep/*.md" --force-search
```

> Each path owns a directory: `work/<topic-slug>/` for comprehensive
> research, or `work/deep/`, `work/batch/`, and `work/enrich/` for the focused
> paths (a symlink to a sibling project's `work/` is fine).

## CLI Reference

### `research-single-topic` (`research_runner.py`)

| Command | Option | Description |
|---------|--------|-------------|
| `run` | `--query` | Research query (required) |
| `run` | `--output` | Markdown report path (required) |
| `run` | `--main-topic` | Baseline topic the query must cover in full (omit for the baseline) |
| `run` | `--mode` | `fast` / `standard` / `heavy` / `max` (default: `fast`) |
| `run` | `--no-wait` | Submit and exit; state in `work/deep/tmp_state.json` |
| `run` | `--max-cost` | Abort if estimate exceeds USD (default: `3.0`) |
| `run` | `--hitl` | Enable `plan_review` / `source_review` checkpoints |
| `run` | `--no-anchor` | Do not attach the main topic to the submitted query |
| `run` | `--allow-drift` | Downgrade scope-check errors to warnings (also permits a narrow query) |

With `--main-topic`, `run` aborts when the query shares no terminology with
the topic (wrong subject) or covers less than half of it (narrowed to one
facet — that is `research-multi-angle`'s shape).
| `status` | `--task-id` | Task ID to poll (required) |
| `status` | `--output` | Path to save report if completed |
| `respond` | `--task-id` | Task ID awaiting input (required) |
| `respond` | `--response-file` | JSON checkpoint response (required) |
| `enrich-check` | `--baseline` | Baseline report (default: `work/deep/research_init.md`) |
| `enrich-check` | `--deep` | Heavy report (default: `work/deep/research_deep.md`) |
| `enrich-check` | `--main-topic` | Topic to judge drift against (default: the baseline's title) |
| `enrich-check` | `--allow-drop` | Baseline facet left out on purpose (substring, repeatable) |

### `research-multi-angle` (`research_runner.py`)

| Command | Option | Description |
|---------|--------|-------------|
| `single` | `--query` | Research query (required) |
| `single` | `--output` | Markdown report path (required) |
| `single` | `--main-topic` | Parent topic to anchor the query to |
| `single` | `--mode` | `fast` / `standard` / `heavy` / `max` (default: `fast`) |
| `single` | `--no-wait` | Submit and exit without polling |
| `single` | `--max-cost` | Max allowed cost in USD (default: `3.0`) |
| `batch` | `--queries-file` | JSON with `queries` list (required) |
| `batch` | `--output-dir` | Reports + `manifest.json` directory (required) |
| `batch` | `--name` | Batch name (default: `Batch Research Task`) |
| `batch` | `--mode` | `fast` / `standard` / `heavy` / `max` (default: `standard`) |
| `batch` | `--no-wait` | Submit and exit without polling |
| `batch` | `--max-cost` | Max allowed cost in USD (default: `3.0`) |
| `batch` | `--max-queries` | Fan-out cap; `0` = unlimited (default: `12`) |
| `status` | `--batch-id` | Batch ID to check (required) |
| `status` | `--output-dir` | Directory to save results if completed |
| `retry` | `--manifest` | Prior `manifest.json` (required) |
| `retry` | `--output-dir` | Directory for retried reports (required) |
| `retry` | `--mode` | Mode for retried tasks (default: `fast`) |
| `retry` | `--no-wait` | Submit retry and exit without polling |
| `retry` | `--max-cost` | Max allowed cost in USD (default: `3.0`) |
| `scope-check` | `--manifest` | Manifest to audit (default: `work/batch/manifest.json`) |
| `scope-check` | `--output-dir` | Directory holding the reports (default: manifest dir) |
| `scope-check` | `--queries-file` | Ideas file to read `anchor_terms` from |
| `single` / `batch` / `retry` | `--no-anchor` | Do not attach the main topic to submitted queries |
| `single` / `batch` / `retry` | `--allow-drift` | Downgrade scope-check errors to warnings |

### `research-verify` (`verify_references.py`)

| Command | Option | Description |
|---------|--------|-------------|
| `verify` / `retry` | `--input` | Glob or file, recursive (default: `work/**/*.md`) |
| `verify` / `retry` | `--rate` | Max OpenAlex requests/sec (default: `5`) |
| `verify` / `retry` | `--sim-threshold` | Title similarity threshold (default: `0.8`) |
| `verify` / `retry` | `--max-cost` | Abort if estimated OpenAlex cost exceeds USD |
| `verify` / `retry` | `--retries` | Per-request retries for 429/5xx/network (default: `4`) |
| `verify` / `retry` | `--backoff-base` | Retry backoff base seconds (default: `1.0`) |
| `verify` / `retry` | `--backoff-cap` | Retry backoff cap seconds (default: `30`) |
| `verify` / `retry` | `--cache` | Cache path, or `auto` for one per report directory (default: `auto`) |
| `verify` / `retry` | `--no-cache` | Disable persistent cache |
| `verify` / `retry` | `--refresh-cache` | Ignore cache and refresh entries |
| `retry` | `--refs` | Specific `.json` sidecar or glob |
| `retry` | `--force-search` | Skip singleton lookup; force title search |

## Input/Output

One directory per skill, all under `work/`.

```text
work/deep/
├── research_init.md              # fast baseline report
├── research_idea.md              # refined query + scope contract
├── research_deep.md              # heavy report on the same topic
├── research_deep.json            # research-verify sidecar (audit only)
└── tmp_*.json                    # async + HITL state, removed on success
```

```text
work/<topic-slug>/
├── research_init.md              # fast baseline report
├── research_idea.md              # refined full-scope query
├── research_deep.md              # heavy report
├── ideas.json                    # anchored gaps + drill-downs
├── researchNN_*.md               # standard facet reports
├── manifest.json                 # batch outcomes + anchors
└── tmp_state.json                # async state, removed on success
```

```text
work/batch/
├── research_init.md              # fast baseline report
├── ideas.json                    # anchored query list
├── researchNN_*.md               # per-query reports
├── manifest.json                 # task outcomes + anchors
└── tmp_state.json                # async state, removed on success
```

```text
work/enrich/
├── brief.md                      # content intent, gaps, scope contract
├── ideas.json                    # anchored enrichment tracks
├── researchNN_*.md               # focused enrichment reports
├── manifest.json
└── tmp_state.json                # async state, removed on success
```

Each of those directories also gets an `openalex_cache.json` once you run verify — a per-directory cache of confirmed lookups (gitignored). Pass `--cache PATH` to share one instead.

Enrich inputs are **whatever you provide** — notes, drafts, reports, articles,
outlines, presentations, or pasted text under any filename. Nothing is
globbed or guessed.

### Ideas format

```json
{
  "main_topic": "Must match the baseline topic",
  "anchor_terms": ["distinctive phrase 1", "distinctive phrase 2"],
  "anchor_headings": ["1. Baseline heading", "2. Baseline heading"],
  "queries": [
    {"id": "Q01", "anchor": "1. Baseline heading", "query": "Deeper drill-down into that facet"},
    {"id": "Q02", "anchor": "2. Baseline heading", "query": "Deeper drill-down into that facet"}
  ]
}
```

The runner attaches `main_topic` to every submitted query and rejects queries that share no distinctive terminology with it — before spending anything. Anchors land in `manifest.json` so retries and `scope-check` stay on topic. A plain `"queries": ["...", "..."]` list still works, but runs unanchored.

### Cost reference

| Mode | Approx. cost / task | Suggested `--max-cost` |
|------|---------------------|------------------------|
| `fast` | ~$0.10 | $1.00 |
| `standard` | ~$0.50 | $2.00 |
| `heavy` | ~$2.50 | $5.00 |
| `max` | ~$15.00 | $20.00 |

Per path: comprehensive ≈ $0.10 + $2.50 + up to 12 × $0.50
(~$8.60; submission limits `$1.00` / `$5.00` / `$7.00`), single-topic ≈
$0.10 + $2.50, multi-angle ≈ $0.10 + up to 12 × $0.50
(`--max-cost 7.00`), enrich ≈ `query_count × $0.10`.

Estimate ≈ `num_queries × mode_cost`; runners abort before the API call if over `--max-cost`.

## Configuration

Copy `.env.example` → `.env`. Priority: CLI flags > env vars > INI sections.

| Section | Used by | Key settings |
|---------|---------|--------------|
| *(preamble)* | External tools | `MINIMAX_API_KEY` |
| `[valyu]` | Comprehensive / single-topic / multi-angle / enrich runners | `api_key`, `categories` |
| `[openalex]` | research-verify | `api_key`, `mailto` (both optional) |

- **Valyu** — `VALYU_API_KEY` overrides `[valyu] api_key`
- **OpenAlex** — optional; verify works without it. A key ([free](https://openalex.org/settings/api)) raises the daily cap, and `mailto` joins the polite pool. `OPENALEX_API_KEY` / `OPENALEX_MAILTO` override the INI values
- **Categories** — `research`, `healthcare`, `patents`, `markets`, `company`,
  `economic`, `predictions`, `legal`, `politics`, `cybersecurity`,
  `transportation` (omit to search all; `research-comprehensive` explicitly
  pins `research`, while content enrichment usually prefers unset/all so it
  can draw from the most suitable sources). `VALYU_CATEGORIES=` clears the
  INI value for one run
- **Never commit `.env`** — only `.env.example` with placeholders

```ini
MINIMAX_API_KEY=your-minimax-api-key-here

[valyu]
api_key = your-valyu-api-key-here
categories = research

[openalex]
api_key = your-openalex-api-key-here
mailto = you@example.com
```

## License

MIT — see [LICENSE](LICENSE).

---

**Happy researching! 🧪✨** Fast baselines, deep dives, and citation-ready reports — without the API grind.
