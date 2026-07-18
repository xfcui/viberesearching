# VibeResearching ✨

**Turn a topic into cited, multi-depth research — without babysitting the API.** Cursor skills + Valyu DeepResearch runners handle baselines, parallel facets, HITL checkpoints, and OpenAlex citation audits.

## Why VibeResearching? 🚀

- **Go Deeper Fast** — Fast baseline, then heavy/max dive or parallel facet batches
- **Stay In Budget** — Cost guardrails abort before overspend (`--max-cost`)
- **Recover Gracefully** — Async submit/poll, batch retry, persistent OpenAlex cache
- **Talk-Ready Craft** — Enrich storytelling/visuals from idea + outline (`enrich-research`)

## Features

- 🧪 **Hierarchical Deep Research** — Fast → one in-scope deep query → heavy/max with optional HITL
- ⚡ **Parallel Batch Research** — Decompose facets → concurrent Valyu tasks → retry failures
- 🎨 **Enrich Research** — Fast-mode craft research for talks (`work/research/*`)
- 📚 **OpenAlex Verify** — Audit `## Sources` into sidecar JSON (never mutates reports)
- 📄 **PDF → Markdown** — marker-pdf conversion with pdfplumber/pypdf fallback
- 🚢 **Ship It** — Secret-scan + pytest gate before commit/push

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env   # add Valyu (+ optional OpenAlex / MiniMax) keys
```

## Pipeline

Pick a path — **deep**, **batch**, or **enrich** — then optionally **verify**:

```bash
# 1a. Deep: fast baseline → heavy dive
python .cursor/skills/deep-research/scripts/research_runner.py run \
  --query "YOUR_TOPIC" --output output/research_init.md --mode fast

# 1b. Batch: baseline → ideas.json → parallel facets
python .cursor/skills/batch-research/scripts/research_runner.py single \
  --query "YOUR_TOPIC" --output output/research_init.md --mode fast
python .cursor/skills/batch-research/scripts/research_runner.py batch \
  --queries-file output/ideas.json --output-dir output --mode fast --no-wait

# 1c. Enrich (talk craft): idea.md + outline_*.md → work/research/
#    (agent skill; uses the batch runner under the hood)

# 2. Optional: verify citations via OpenAlex
python .cursor/skills/verify-references/scripts/verify_references.py verify \
  --input "output/*.md" --max-cost 1.0
```

> 💡 Deep/batch artifacts land in `output/`. Enrich writes under `work/research/` (symlink to sibling VibeSliding `work/` is fine). Use Cursor skills `deep-research`, `batch-research`, `enrich-research`, or `verify-references` to drive the full workflow.

## Usage Examples

```bash
# Deep: async heavy dive + poll
python .cursor/skills/deep-research/scripts/research_runner.py run \
  --query "NARROWED_QUERY" --output output/research_deep.md \
  --mode heavy --no-wait --max-cost 5.00
python .cursor/skills/deep-research/scripts/research_runner.py status \
  --task-id "TASK_ID" --output output/research_deep.md

# Deep: HITL checkpoint reply
python .cursor/skills/deep-research/scripts/research_runner.py respond \
  --task-id "TASK_ID" --response-file output/checkpoint_response.json

# Batch: status + retry failed tasks
python .cursor/skills/batch-research/scripts/research_runner.py status \
  --batch-id "BATCH_ID" --output-dir output
python .cursor/skills/batch-research/scripts/research_runner.py retry \
  --manifest output/manifest.json --output-dir output --mode fast --max-cost 2.00

# Enrich: craft batch into work/research/
python .cursor/skills/batch-research/scripts/research_runner.py batch \
  --queries-file work/research/ideas.json --output-dir work/research \
  --name "Talk enrich" --mode fast --no-wait --max-cost 2.00

# Verify: re-run unresolved sidecars
python .cursor/skills/verify-references/scripts/verify_references.py retry \
  --input "output/*.md" --force-search

# PDF → Markdown
python .cursor/skills/convert-pdf-to-markdown/scripts/convert.py \
  --input path/to/document.pdf --output output/document.md

# Ship gate
python .cursor/skills/ship-it/scripts/ship_it.py check
```

## CLI Reference

### `deep-research` (`research_runner.py`)

| Command | Option | Description |
|---------|--------|-------------|
| `run` | `--query` | Research query (required) |
| `run` | `--output` | Markdown report path (required) |
| `run` | `--mode` | `fast` / `standard` / `heavy` / `max` (default: `fast`) |
| `run` | `--no-wait` | Submit and exit; state in `output/active_tasks.json` |
| `run` | `--max-cost` | Abort if estimate exceeds USD (default: `3.0`) |
| `run` | `--hitl` | Enable `plan_review` / `source_review` checkpoints |
| `status` | `--task-id` | Task ID to poll (required) |
| `status` | `--output` | Path to save report if completed |
| `respond` | `--task-id` | Task ID awaiting input (required) |
| `respond` | `--response-file` | JSON checkpoint response (required) |

### `batch-research` (`research_runner.py`)

| Command | Option | Description |
|---------|--------|-------------|
| `single` | `--query` | Research query (required) |
| `single` | `--output` | Markdown report path (required) |
| `single` | `--mode` | `fast` / `standard` / `heavy` / `max` (default: `fast`) |
| `single` | `--no-wait` | Submit and exit without polling |
| `single` | `--max-cost` | Max allowed cost in USD (default: `3.0`) |
| `batch` | `--queries-file` | JSON with `queries` list (required) |
| `batch` | `--output-dir` | Reports + `manifest.json` directory (required) |
| `batch` | `--name` | Batch name (default: `Batch Research Task`) |
| `batch` | `--mode` | `fast` / `standard` / `heavy` / `max` (default: `fast`) |
| `batch` | `--no-wait` | Submit and exit without polling |
| `batch` | `--max-cost` | Max allowed cost in USD (default: `3.0`) |
| `status` | `--batch-id` | Batch ID to check (required) |
| `status` | `--output-dir` | Directory to save results if completed |
| `retry` | `--manifest` | Prior `manifest.json` (required) |
| `retry` | `--output-dir` | Directory for retried reports (required) |
| `retry` | `--mode` | Mode for retried tasks (default: `fast`) |
| `retry` | `--no-wait` | Submit retry and exit without polling |
| `retry` | `--max-cost` | Max allowed cost in USD (default: `3.0`) |

### `verify-references` (`verify_references.py`)

| Command | Option | Description |
|---------|--------|-------------|
| `verify` / `retry` | `--input` | Glob or file (default: `output/*.md`) |
| `verify` / `retry` | `--rate` | Max OpenAlex requests/sec (default: `5`) |
| `verify` / `retry` | `--sim-threshold` | Title similarity threshold (default: `0.8`) |
| `verify` / `retry` | `--max-cost` | Abort if estimated OpenAlex cost exceeds USD |
| `verify` / `retry` | `--retries` | Per-request retries (default: `4`) |
| `verify` / `retry` | `--backoff-base` | Retry backoff base seconds (default: `1.0`) |
| `verify` / `retry` | `--backoff-cap` | Retry backoff cap seconds (default: `30`) |
| `verify` / `retry` | `--cache` | Cache path (default: `output/openalex_cache.json`) |
| `verify` / `retry` | `--no-cache` | Disable persistent cache |
| `verify` / `retry` | `--refresh-cache` | Ignore cache and refresh entries |
| `retry` | `--refs` | Specific `.json` sidecar or glob |
| `retry` | `--force-search` | Skip singleton lookup; force title search |

### `convert-pdf-to-markdown` (`convert.py`)

| Option | Description |
|--------|-------------|
| `--input`, `-i` | Input PDF (required) |
| `--output`, `-o` | Output `.md` (default: beside input) |
| `--output-dir`, `-d` | Dir for markdown + images |
| `--fallback` | Skip marker-pdf; use pdfplumber/pypdf |

### `ship-it` (`ship_it.py`)

| Command | Option | Description |
|---------|--------|-------------|
| *(global)* | `--repo-root` | Repository root (default: discover from cwd) |
| `check` | `--staged` | Scan only staged files |
| `check` | `pytest_args` | Extra args forwarded to pytest |
| `test` | `pytest_args` | Extra args forwarded to pytest |
| `scan` | `--staged` | Scan only staged files |

## Input/Output

### Output Directory (deep / batch)

```
output/
├── research_init.md              # fast baseline report
├── research_deep.md              # heavy/max deep-dive report
├── deep_research_idea.md         # deep-research ideation note
├── ideas.json                    # batch query list
├── manifest.json                 # batch task outcomes
├── active_tasks.json             # async single-task state
├── active_batches.json           # async batch state
├── openalex_cache.json           # OpenAlex lookup cache (gitignored)
├── research_init.json            # verify-references sidecar (audit only)
└── researchNN_*.md               # per-query batch reports
```

### Enrich Directory (talk craft)

```
work/research/
├── brief.md                      # design note + content_page_count
├── ideas.json                    # batch payload (S/V/X tracks)
├── batch_state.json              # ids, tracks, poll command
├── 00_research_init.md           # optional baseline
├── researchNN_*.md               # batch reports
├── manifest.json
└── active_batches.json
```

### Ideas Format

```json
{
  "main_topic": "Must match the baseline topic",
  "queries": [
    "Deeper drill-down into baseline facet 1",
    "Deeper drill-down into baseline facet 2"
  ]
}
```

Queries may also be `{"query": "..."}` objects (`id` / `track` kept locally; runner sends query strings only).

### Cost Reference

| Mode | Approx. cost / task | Suggested `--max-cost` |
|------|---------------------|------------------------|
| `fast` | ~$0.10 | $1.00 |
| `standard` | ~$0.50 | $2.00 |
| `heavy` | ~$2.50 | $5.00 |
| `max` | ~$15.00 | $20.00 |

Estimate ≈ `num_queries × mode_cost`; runners abort before API call if over `--max-cost`.

## Configuration

Copy `.env.example` → `.env`. Priority: CLI flags > env vars > INI sections.

| Section | Used by | Key settings |
|---------|---------|--------------|
| *(preamble)* | External tools | `MINIMAX_API_KEY` |
| `[valyu]` | Deep / batch / enrich runners | `api_key`, `categories` |
| `[openalex]` | verify-references | `api_key` |

- **Valyu** — `VALYU_API_KEY` overrides `[valyu] api_key`
- **OpenAlex** — `OPENALEX_API_KEY` overrides `[openalex] api_key` ([free key](https://openalex.org/settings/api))
- **Categories** — `research`, `healthcare`, `patents`, `markets`, `company`, `economic`, `predictions`, `legal`, `politics`, `cybersecurity`, `transportation` (omit to search all; prefer unset/all for enrich/talk craft)
- **Never commit `.env`** — only `.env.example` with placeholders

```ini
MINIMAX_API_KEY=your-minimax-api-key-here

[valyu]
api_key = your-valyu-api-key-here
categories = research

[openalex]
api_key = your-openalex-api-key-here
```

## License

MIT — see [LICENSE](LICENSE).

---

**Happy researching! 🧪✨** Fast baselines, deep dives, and citation-ready reports — without the API grind.
