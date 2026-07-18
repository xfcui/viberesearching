# Valyu DeepResearch Workspace

This workspace provides powerful tools and automation scripts to conduct advanced, multi-step deep research and parallel batch research on any topic, powered by the Valyu DeepResearch API. It contains custom runner scripts and pre-configured Cursor Agent Skills to automate complex research workflows, manage cost guardrails, handle Human-in-the-Loop (HITL) checkpoints, and perform parallel querying with automated error retries.

---

## Directory Structure

```text
.
├── .cursor/
│   ├── rules/
│   │   └── env-security.mdc       # Environment security and secrets policies
│   └── skills/
│       ├── deep-research/         # Hierarchical Deep Research workflow
│       │   ├── scripts/
│       │   │   └── research_runner.py
│       │   └── SKILL.md
│       ├── batch-research/        # Parallel Batch Research workflow
│       │   ├── scripts/
│       │   │   └── research_runner.py
│       │   └── SKILL.md
│       └── verify-references/     # OpenAlex reference verification
│           ├── scripts/
│           │   └── verify_references.py
│           └── SKILL.md
├── output/                        # Output directory for reports and state tracking
│   ├── active_tasks.json          # Tracks submitted single async tasks
│   ├── active_batches.json        # Tracks submitted async batches
│   ├── manifest.json              # Record of completed/failed tasks in a batch
│   ├── openalex_cache.json        # Persistent OpenAlex lookup cache (gitignored)
│   └── *.md                       # Generated research reports
├── .env.example                   # Configuration template for API keys and options
├── requirements.txt               # Workspace python dependencies
└── README.md                      # This file
```

---

## Prerequisites & Installation

### 1. Install Dependencies

Ensure Python 3.10+ is installed, then install the required Python packages:

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Open `.env` and fill in your credentials. The workspace uses both standard environment variables and a custom `[valyu]` INI section.

```ini
MINIMAX_API_KEY=your-minimax-api-key-here

[valyu]
api_key = your-valyu-api-key-here
categories = research

[openalex]
api_key = your-openalex-api-key-here
```

- **Priority order**: Command-line arguments > Environment variables (`VALYU_API_KEY`, `OPENALEX_API_KEY`) > INI sections inside `.env`.
- **Allowed Datasource Categories**: `research`, `healthcare`, `patents`, `markets`, `company`, `economic`, `predictions`, `legal`, `politics`, `cybersecurity`, `transportation`. Omit or comment out `categories` to search all sources.

---

## Workflow 1: Hierarchical Deep Research

The **Hierarchical Deep Research** skill (`deep-research`) conducts deep-dive, multi-phase research. Instead of running a single long query, it establishes a baseline, allows for focused sub-topic ideation, and executes high-fidelity deep-dive research with human guidance if needed.

### 4-Phase Process

1. **Phase 1: Fast Mode Baseline**: Run initial research in `fast` mode to establish a broad overview of the topic.
2. **Phase 2: Analysis & Deep Ideation**: Analyze the baseline report to uncover gaps, structural limitations, or high-potential sub-topics. Formulate a highly specific, deep-dive query and save it to `output/deep_research_idea.md`.
3. **Phase 3: Heavy Mode Deep Research**: Submit the detailed query in `heavy` or `max` mode. For long-running tasks, run asynchronously (`--no-wait`) to avoid blocking.
4. **Phase 4: Synthesis & Mode Comparison**: Compare both generated reports and present a comprehensive comparative synthesis (findings, sources, and a cost-benefit analysis).

### Commands & Subcommands

The deep research runner is located at `.cursor/skills/deep-research/scripts/research_runner.py`.

#### `run`
Submit a research task.

```bash
python .cursor/skills/deep-research/scripts/research_runner.py run \
  --query "YOUR_RESEARCH_QUERY" \
  --output "output/research_init.md" \
  --mode "fast" \
  --max-cost 3.00
```

**Key Flags for `run`**:
- `--query`: The research query string (required).
- `--output`: Filepath to write the completed markdown report (required).
- `--mode`: Valyu research depth. Choices: `fast`, `standard`, `heavy`, `max`.
- `--no-wait`: Submits the task and exits immediately (recommended for `heavy` and `max` modes). Saves state to `output/active_tasks.json`.
- `--max-cost`: Aborts task submission if estimated cost exceeds this limit in USD.
- `--hitl`: Enables Human-in-the-Loop checkpoints (`plan_review` and `source_review`).

#### `status`
Check the status of an asynchronously submitted task and download results upon completion.

```bash
python .cursor/skills/deep-research/scripts/research_runner.py status \
  --task-id "YOUR_TASK_ID" \
  --output "output/research_deep.md"
```

#### `respond`
Reply to a Human-in-the-Loop checkpoint when a task is paused in the `awaiting_input` state.

```bash
python .cursor/skills/deep-research/scripts/research_runner.py respond \
  --task-id "YOUR_TASK_ID" \
  --response-file "output/checkpoint_response.json"
```

---

## Workflow 2: Parallel Batch Research

The **Batch Research** skill (`batch-research`) runs multiple deep research tasks concurrently. It is highly optimized for exploring several distinct facets or sub-ideas of a main subject simultaneously.

### 4-Phase Process

1. **Phase 1: Initial Research**: Perform single research on the main topic in `fast` mode.
2. **Phase 2: Analysis & Ideation**: Brainstorm up to 12 distinct, high-quality queries expanding on initial findings and save them in a structured JSON file at `output/ideas.json`.
3. **Phase 3: Batch Research Execution**: Submit the queries file to execute the parallel research tasks.
4. **Phase 4: Verification, Retry & Synthesis**: Inspect progress. If any concurrent task fails, run the automated `retry` command to re-submit only the failed queries. Present a clean synthesis table showing filepaths and major findings.

### Commands & Subcommands

The batch research runner is located at `.cursor/skills/batch-research/scripts/research_runner.py`.

#### `single`
Runs a single, synchronous deep research task (similar to deep research `run` without HITL support).

```bash
python .cursor/skills/batch-research/scripts/research_runner.py single \
  --query "YOUR_QUERY" \
  --output "output/research_init.md" \
  --mode "fast"
```

#### `batch`
Submit a batch of queries to run concurrently.

```bash
python .cursor/skills/batch-research/scripts/research_runner.py batch \
  --queries-file "output/ideas.json" \
  --output-dir "output" \
  --name "My Batch Name" \
  --mode "fast" \
  --max-cost 5.00
```

**Input File Format (`output/ideas.json`)**:
```json
{
  "queries": [
    "Query 1 text...",
    "Query 2 text..."
  ]
}
```

#### `status`
Check the progress of a batch of research tasks and download completed reports.

```bash
python .cursor/skills/batch-research/scripts/research_runner.py status \
  --batch-id "YOUR_BATCH_ID" \
  --output-dir "output"
```

#### `retry`
Identify failed or cancelled tasks in a completed batch from its `manifest.json`, re-submit them as a new batch, and merge the final results back into the original manifest.

```bash
python .cursor/skills/batch-research/scripts/research_runner.py retry \
  --manifest "output/manifest.json" \
  --output-dir "output" \
  --mode "fast" \
  --max-cost 2.00
```

---

## Workflow 3: Reference Verification & Enrichment

The **Verify References** skill (`verify-references`) checks citations in research reports against OpenAlex and writes audit-only sidecar JSON files. It defaults to `output/*.md` and never modifies the source reports.

### Process

1. **Verify**: Parse each report's `## Sources` block, resolve references via OpenAlex (DOI/PMID/PMCID singleton lookups first, title search fallback), deduplicate across files, and write `{file}.json` (e.g. `research_init.md` → `research_init.json`).
2. **Retry (optional)**: Re-run only unverified or errored records and merge results back into the sidecar files.

### Commands

The verify runner is located at `.cursor/skills/verify-references/scripts/verify_references.py`.

#### `verify`

```bash
python .cursor/skills/verify-references/scripts/verify_references.py verify \
  --max-cost 1.0
```

**Key flags**: `--input` (default `output/*.md`), `--rate 5`, `--sim-threshold 0.8`, `--max-cost`, `--no-cache`, `--refresh-cache`.

#### `retry`

```bash
python .cursor/skills/verify-references/scripts/verify_references.py retry
```

Re-processes only failed/unverified records from existing `{file}.json` sidecars. Use `--force-search` to skip singleton lookup and force title search.

### OpenAlex notes

- Free API key at [openalex.org/settings/api](https://openalex.org/settings/api) — configure under `[openalex] api_key` in `.env`.
- Singleton lookups (DOI, PMID, PMCID) are free; title filter calls cost ~$0.0001 each.
- Persistent cache at `output/openalex_cache.json` avoids redundant lookups across runs.

---

## Cost Guidelines & Safety

To prevent unexpected API overspend, both runner scripts enforce cost check guardrails. They calculate expected cost as `num_queries × mode_cost_per_task` and abort before invoking the API if the estimate exceeds `--max-cost` (default is $3.00 if not specified).

### Estimation Reference

| Mode | Approximate Cost per Task | Recommended `--max-cost` |
|---|---|---|
| `fast` | $0.10 | $1.00 |
| `standard` | $0.50 | $2.00 |
| `heavy` | $2.50 | $5.00 |
| `max` | $15.00 | $20.00 |

### Examples for Batches
- 10 parallel queries in `fast` mode ($1.00 estimated): set `--max-cost 2.00`
- 10 parallel queries in `standard` mode ($5.00 estimated): set `--max-cost 7.00`
- 12 parallel queries in `heavy` mode ($30.00 estimated): set `--max-cost 35.00`

---

## Environment & Secrets Security Policy

To maintain confidentiality of API credentials and keys:

1. **Do Not Commit `.env`**: The `.env` file containing real keys must never be staged, committed, or pushed. It is listed in `.gitignore` to prevent accidental inclusion.
2. **Template Placeholder Usage**: Only `.env.example` containing placeholder values should be committed to track configuration requirements.
3. **No Hardcoding**: API keys and proxy credentials must never be hardcoded in Python scripts, tests, markdown files, or code comments.
4. **Key Redaction**: If keys need to be logged or printed during debugging, they should be redacted (e.g., `val_...last4` or `sk-...last4`).
