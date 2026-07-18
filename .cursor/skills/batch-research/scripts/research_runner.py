#!/usr/bin/env python3
import os
import sys
import json
import time
import argparse
import configparser
from pathlib import Path
from typing import Any, Optional, Set, Union
from dotenv import load_dotenv
from valyu import Valyu

MODE_COSTS = {"fast": 0.10, "standard": 0.50, "heavy": 2.50, "max": 15.00}
DEFAULT_STATE_FILE = Path("output/active_batches.json")


def active_batches_path(output_dir: Optional[Union[str, Path]] = None) -> Path:
    """Prefer {output_dir}/active_batches.json; fall back to output/active_batches.json."""
    if output_dir:
        return Path(output_dir) / "active_batches.json"
    return DEFAULT_STATE_FILE


def find_env_file() -> Path:
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        env_file = parent / ".env"
        if env_file.exists():
            return env_file
    return Path.cwd() / ".env"


def read_valyu_section(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    try:
        text = env_path.read_text(encoding="utf-8")
        start = text.find("[valyu]")
        if start == -1:
            return {}
        parser = configparser.ConfigParser()
        parser.read_string(text[start:])
        if not parser.has_section("valyu"):
            return {}
        return {key: value for key, value in parser.items("valyu") if key != "DEFAULT"}
    except Exception:
        return {}


def get_valyu_client() -> Valyu:
    env_path = find_env_file()
    load_dotenv(env_path)
    section = read_valyu_section(env_path)
    api_key = os.getenv("VALYU_API_KEY") or section.get("api_key", "").strip()
    if not api_key:
        print("Error: VALYU_API_KEY not found in environment or [valyu] section of .env.", file=sys.stderr)
        sys.exit(1)
    return Valyu(api_key=api_key)


def get_search_config() -> Optional[dict[str, Any]]:
    env_path = find_env_file()
    load_dotenv(env_path)
    section = read_valyu_section(env_path)
    categories = os.getenv("VALYU_CATEGORIES") or section.get("categories")
    if categories:
        categories = categories.strip()
        parts = [part.strip() for part in categories.split(",") if part.strip()]
        if parts:
            return {"category": parts[0]}
    return None


def check_cost_limit(mode: str, max_cost: Optional[float], task_count: int = 1):
    """Abort if estimated cost exceeds --max-cost safety limit."""
    if max_cost is None:
        return
    estimated = MODE_COSTS.get(mode, 0.50) * task_count
    if estimated > max_cost:
        print(
            f"Error: Estimated cost ${estimated:.2f} ({task_count} task(s) x ${MODE_COSTS.get(mode, 0.50):.2f}/{mode}) "
            f"exceeds --max-cost limit of ${max_cost:.2f}. Aborting.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"Cost check passed: estimated ${estimated:.2f} <= limit ${max_cost:.2f}")


def load_queries(queries_file: Path) -> list[dict[str, str]]:
    """Parse a JSON queries file into a list of query dicts."""
    if not queries_file.exists():
        print(f"Error: Queries file '{queries_file}' does not exist.", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(queries_file.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "queries" in data:
            queries_raw = data["queries"]
        else:
            queries_raw = data

        if not isinstance(queries_raw, list):
            raise ValueError("Root or 'queries' must be a list")

        queries = []
        for item in queries_raw:
            if isinstance(item, str):
                queries.append({"query": item})
            elif isinstance(item, dict) and "query" in item:
                queries.append({"query": item["query"]})
            else:
                print(f"Warning: Skipping invalid item: {item}", file=sys.stderr)
        return queries
    except Exception as e:
        print(f"Error: Failed to parse queries file as JSON: {e}", file=sys.stderr)
        sys.exit(1)


def save_batch_results(client, batch_id: str, output_dir: Path) -> list[dict]:
    """Download all batch task results and return the manifest entries."""
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Fetching results and saving to {output_dir}...")

    manifest = []
    last_key = None
    task_count = 0

    while True:
        results = client.batch.list_tasks(
            batch_id,
            include_output=True,
            last_key=last_key,
        )

        for task in results.tasks:
            task_count += 1
            query_clean = "".join(c if c.isalnum() or c in " _-" else "_" for c in task.query)
            query_slug = query_clean.replace(" ", "_").replace("/", "_").replace("'", "").lower()[:50]
            filename = f"research{task_count:02d}_{query_slug}.md"
            filepath = output_dir / filename

            output_text = task.output or "No output generated."
            filepath.write_text(output_text, encoding="utf-8")
            print(f"  Saved: {filename}")

            sources_list = []
            if task.sources:
                for src in task.sources:
                    sources_list.append({
                        "title": getattr(src, "title", "Unknown"),
                        "url": getattr(src, "url", ""),
                    })

            manifest.append({
                "task_id": task.task_id,
                "query": task.query,
                "status": task.status,
                "cost": task.cost,
                "filename": filename,
                "sources": sources_list,
                "error": getattr(task, "error", None),
            })

        last_key = results.pagination.last_key if results.pagination else None
        if not last_key:
            break

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Saved manifest to {manifest_path}")
    return manifest


def save_active_batch(batch_id: str, name: str, mode: str, output_dir: str, query_count: int):
    """Persist batch metadata so `status` can retrieve it later."""
    state_path = active_batches_path(output_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    batches = []
    if state_path.exists():
        try:
            batches = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            batches = []

    batches.append({
        "batch_id": batch_id,
        "name": name,
        "mode": mode,
        "output_dir": output_dir,
        "query_count": query_count,
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    })
    state_path.write_text(json.dumps(batches, indent=2, ensure_ascii=False), encoding="utf-8")
    return state_path


def _remove_from_active(batch_id: str, output_dir: Optional[Union[str, Path]] = None):
    # Check both the run's output dir and the legacy default path.
    candidates = []
    if output_dir:
        candidates.append(active_batches_path(output_dir))
    candidates.append(DEFAULT_STATE_FILE)
    seen: Set[Path] = set()
    for state_path in candidates:
        state_path = Path(state_path)
        if state_path in seen or not state_path.exists():
            continue
        seen.add(state_path)
        try:
            batches = json.loads(state_path.read_text(encoding="utf-8"))
            batches = [b for b in batches if b.get("batch_id") != batch_id]
            state_path.write_text(json.dumps(batches, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Subcommands
# ──────────────────────────────────────────────────────────────────────────────


def handle_single(args):
    client = get_valyu_client()
    query = args.query
    output_path = Path(args.output)
    mode = args.mode
    no_wait = getattr(args, "no_wait", False)
    max_cost = getattr(args, "max_cost", None)

    check_cost_limit(mode, max_cost)

    print(f"Creating deep research task in '{mode}' mode...")
    print(f"Query: {query}")

    kwargs: dict[str, Any] = {
        "query": query,
        "mode": mode,
        "output_formats": ["markdown"],
    }

    search_config = get_search_config()
    if search_config:
        print(f"Applying search configuration: {search_config}")
        kwargs["search"] = search_config

    task = client.deepresearch.create(**kwargs)

    if not task.success:
        print(f"Error: Failed to create task. Response: {task}", file=sys.stderr)
        sys.exit(1)

    print(f"Task created successfully. Task ID: {task.deepresearch_id}")

    if no_wait:
        state_path = Path("output/active_tasks.json")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tasks = []
        if state_path.exists():
            try:
                tasks = json.loads(state_path.read_text(encoding="utf-8"))
            except Exception:
                tasks = []
        tasks.append({
            "task_id": task.deepresearch_id,
            "query": query,
            "mode": mode,
            "output": str(output_path),
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        })
        state_path.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Task submitted in --no-wait mode. State saved to {state_path}.")
        print("Use the 'status' command to check progress later.")
        return

    print("Waiting for completion...")

    result = client.deepresearch.wait(
        task.deepresearch_id,
        poll_interval=10,
        on_progress=lambda s: print(f"  Status: {s.status}"),
    )

    if result.status != "completed":
        print(f"Error: Task failed with status '{result.status}'. Details: {result.error}", file=sys.stderr)
        sys.exit(1)

    print("Task completed successfully!")
    print(f"Report cost: ${result.cost:.2f}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_text = result.output or "No output generated."
    output_path.write_text(output_text, encoding="utf-8")
    print(f"Report saved to {output_path}")


def handle_batch(args):
    client = get_valyu_client()
    queries_file = Path(args.queries_file)
    output_dir = Path(args.output_dir)
    name = args.name
    mode = args.mode
    no_wait = getattr(args, "no_wait", False)
    max_cost = getattr(args, "max_cost", None)

    queries = load_queries(queries_file)
    if not queries:
        print("Error: No valid queries found to research.", file=sys.stderr)
        sys.exit(1)

    check_cost_limit(mode, max_cost, task_count=len(queries))

    print(f"Creating a new batch '{name}' in '{mode}' mode with {len(queries)} queries...")
    kwargs: dict[str, Any] = {
        "name": name,
        "mode": mode,
        "output_formats": ["markdown"],
    }

    search_config = get_search_config()
    if search_config:
        print(f"Applying search configuration: {search_config}")
        kwargs["search"] = search_config

    batch = client.batch.create(**kwargs)
    batch_id = batch.batch_id
    print(f"Created batch with ID: {batch_id}")

    print("Adding tasks to the batch...")
    client.batch.add_tasks(batch_id, queries)
    print("Tasks added successfully!")

    if no_wait:
        state_path = save_active_batch(batch_id, name, mode, str(output_dir), len(queries))
        print(f"Batch submitted in --no-wait mode. State saved to {state_path}.")
        print("Use the 'status' command to check progress later.")
        return

    print("Waiting for batch completion (polling every 15 seconds)...")

    def on_progress(status_response):
        counts = status_response.batch.counts
        print(
            f"  Progress: {counts.completed}/{counts.total} completed "
            f"(queued: {counts.queued}, running: {counts.running}, failed: {counts.failed})"
        )

    final = client.batch.wait_for_completion(
        batch_id,
        poll_interval=15,
        on_progress=on_progress,
    )

    print(f"\nBatch finished with status: {final.batch.status}")
    print(f"Total cost: ${final.batch.cost:.2f}")

    save_batch_results(client, batch_id, output_dir)
    print("Batch research completed successfully!")


def handle_status(args):
    """Check the status of a previously submitted batch."""
    client = get_valyu_client()
    batch_id = args.batch_id
    output_dir = Path(args.output_dir) if args.output_dir else None

    print(f"Checking status of batch: {batch_id}")
    status_resp = client.batch.status(batch_id)

    batch_info = status_resp.batch
    batch_status = batch_info.status
    counts = batch_info.counts
    print(f"  Status: {batch_status}")
    print(
        f"  Progress: {counts.completed}/{counts.total} completed "
        f"(queued: {counts.queued}, running: {counts.running}, failed: {counts.failed})"
    )

    if batch_status in ("queued", "running", "in_progress", "processing", "open"):
        print("  Batch is still running. Check back later.")
        return

    if batch_status in ("completed", "completed_with_errors"):
        print(f"  Batch completed! Total cost: ${batch_info.cost:.2f}")
        if output_dir:
            save_batch_results(client, batch_id, output_dir)
            _remove_from_active(batch_id, output_dir)
        else:
            print("  Provide --output-dir to download and save results.")
    else:
        print(f"  Batch ended with status: {batch_status}")


def handle_retry(args):
    """Retry failed tasks from a previous batch using manifest.json."""
    client = get_valyu_client()
    manifest_path = Path(args.manifest)
    output_dir = Path(args.output_dir)
    mode = args.mode
    no_wait = getattr(args, "no_wait", False)
    max_cost = getattr(args, "max_cost", None)

    if not manifest_path.exists():
        print(f"Error: Manifest file '{manifest_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error: Failed to parse manifest: {e}", file=sys.stderr)
        sys.exit(1)

    failed_queries = [
        {"query": entry["query"]}
        for entry in manifest
        if entry.get("status") in ("failed", "cancelled")
    ]

    if not failed_queries:
        print("No failed or cancelled tasks found in manifest. Nothing to retry.")
        return

    print(f"Found {len(failed_queries)} failed/cancelled task(s) to retry.")
    check_cost_limit(mode, max_cost, task_count=len(failed_queries))

    name = f"Retry: {len(failed_queries)} failed tasks"
    kwargs: dict[str, Any] = {
        "name": name,
        "mode": mode,
        "output_formats": ["markdown"],
    }

    search_config = get_search_config()
    if search_config:
        kwargs["search"] = search_config

    batch = client.batch.create(**kwargs)
    batch_id = batch.batch_id
    print(f"Created retry batch with ID: {batch_id}")

    client.batch.add_tasks(batch_id, failed_queries)
    print("Failed tasks re-submitted!")

    if no_wait:
        state_path = save_active_batch(batch_id, name, mode, str(output_dir), len(failed_queries))
        print(f"Retry batch submitted in --no-wait mode. State saved to {state_path}.")
        return

    print("Waiting for retry batch completion...")

    def on_progress(status_response):
        counts = status_response.batch.counts
        print(
            f"  Progress: {counts.completed}/{counts.total} completed "
            f"(queued: {counts.queued}, running: {counts.running}, failed: {counts.failed})"
        )

    final = client.batch.wait_for_completion(batch_id, poll_interval=15, on_progress=on_progress)
    print(f"\nRetry batch finished with status: {final.batch.status}")
    print(f"Total cost: ${final.batch.cost:.2f}")

    retry_manifest = save_batch_results(client, batch_id, output_dir)

    # Merge retry results back into the original manifest
    original_failed_queries = {e["query"] for e in manifest if e.get("status") in ("failed", "cancelled")}
    merged = [e for e in manifest if e["query"] not in original_failed_queries]
    merged.extend(retry_manifest)
    manifest_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Merged retry results back into {manifest_path}")
    print("Retry completed successfully!")


def main():
    parser = argparse.ArgumentParser(
        description="Valyu DeepResearch runner: single tasks, batch research, status polling, and retry."
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Command to run")

    # --- single: run a single deep research task ---
    parser_single = subparsers.add_parser("single", help="Run a single deep research task")
    parser_single.add_argument("--query", required=True, help="The research query to run")
    parser_single.add_argument("--output", required=True, help="Path to save the markdown report")
    parser_single.add_argument(
        "--mode", default="fast", choices=["fast", "standard", "heavy", "max"],
        help="DeepResearch mode (default: fast)",
    )
    parser_single.add_argument("--no-wait", action="store_true", help="Submit and exit without polling")
    parser_single.add_argument("--max-cost", type=float, default=3.0, help="Max allowed cost in USD (default: 3.0)")

    # --- batch: run parallel batch research ---
    parser_batch = subparsers.add_parser("batch", help="Run a batch of deep research tasks")
    parser_batch.add_argument("--queries-file", required=True, help="JSON file with queries list")
    parser_batch.add_argument("--output-dir", required=True, help="Directory to save reports and manifest")
    parser_batch.add_argument("--name", default="Batch Research Task", help="Name of the batch")
    parser_batch.add_argument(
        "--mode", default="fast", choices=["fast", "standard", "heavy", "max"],
        help="DeepResearch mode (default: fast)",
    )
    parser_batch.add_argument("--no-wait", action="store_true", help="Submit and exit without polling")
    parser_batch.add_argument("--max-cost", type=float, default=3.0, help="Max allowed cost in USD (default: 3.0)")

    # --- status: check batch progress ---
    parser_status = subparsers.add_parser("status", help="Check status of a submitted batch")
    parser_status.add_argument("--batch-id", required=True, help="The batch ID to check")
    parser_status.add_argument("--output-dir", default=None, help="Directory to save results if completed")

    # --- retry: re-run failed tasks from a manifest ---
    parser_retry = subparsers.add_parser("retry", help="Retry failed tasks from a previous batch manifest")
    parser_retry.add_argument("--manifest", required=True, help="Path to the manifest.json from a prior batch")
    parser_retry.add_argument("--output-dir", required=True, help="Directory to save retried reports")
    parser_retry.add_argument(
        "--mode", default="fast", choices=["fast", "standard", "heavy", "max"],
        help="DeepResearch mode for retried tasks (default: fast)",
    )
    parser_retry.add_argument("--no-wait", action="store_true", help="Submit retry and exit without polling")
    parser_retry.add_argument("--max-cost", type=float, default=3.0, help="Max allowed cost in USD (default: 3.0)")

    args = parser.parse_args()

    if args.command == "single":
        handle_single(args)
    elif args.command == "batch":
        handle_batch(args)
    elif args.command == "status":
        handle_status(args)
    elif args.command == "retry":
        handle_retry(args)


if __name__ == "__main__":
    main()
