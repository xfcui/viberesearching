#!/usr/bin/env python3
import sys
import json
import time
import argparse
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
from research_env import (  # noqa: E402
    check_cost_limit,
    get_search_config,
    get_valyu_client,
    resolve_work_dir as _resolve_work_dir,
)
from research_scope import (  # noqa: E402
    anchor_query,
    audit_report_scope,
    append_state,
    gate_scope,
    load_scoped_queries,
    purge_tmp,
    tmp_state_path,
)

DEFAULT_WORK_DIR = Path("work/batch")
DEFAULT_MAX_QUERIES = 12


def resolve_work_dir(output: Optional[str]) -> Path:
    return _resolve_work_dir(output, DEFAULT_WORK_DIR)


def check_query_limit(query_count: int, max_queries: Optional[int]):
    """Abort if the ideas file exceeds the skill's fan-out cap (0 = unlimited)."""
    if not max_queries:
        return
    if query_count > max_queries:
        print(
            f"Error: {query_count} queries exceeds the --max-queries cap of {max_queries}. "
            "Trim the ideas file, or pass --max-queries 0 for an uncapped run. Aborting.",
            file=sys.stderr,
        )
        sys.exit(1)


def save_batch_results(client, batch_id: str, output_dir: Path, scope: Optional[dict] = None) -> tuple[list[dict], bool]:
    """Download batch results; return (manifest, all_succeeded)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Fetching results and saving to {output_dir}...")

    scope = scope or {}
    main_topic = scope.get("main_topic", "")
    by_query = {entry.get("submitted", ""): entry for entry in scope.get("entries", [])}

    manifest = []
    last_key = None
    task_count = 0
    all_succeeded = True

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

            if task.status != "completed":
                all_succeeded = False

            sources_list = []
            if task.sources:
                for src in task.sources:
                    sources_list.append({
                        "title": getattr(src, "title", "Unknown"),
                        "url": getattr(src, "url", ""),
                    })

            origin = by_query.get(task.query, {})
            manifest.append({
                "task_id": task.task_id,
                "id": origin.get("id"),
                "query": task.query,
                "main_topic": origin.get("main_topic", main_topic),
                "anchor": origin.get("anchor"),
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
    return manifest, all_succeeded


def finish_batch(output_dir: Path, batch_id: str, all_succeeded: bool):
    """Clean up temp state after a clean run; keep it when retry is still needed."""
    if all_succeeded:
        purge_tmp(output_dir, "batch_id", batch_id)
        print("  Temp state cleaned up.")
    else:
        print("  Some tasks did not complete — temp state kept for 'retry'.")


# ──────────────────────────────────────────────────────────────────────────────
# Subcommands
# ──────────────────────────────────────────────────────────────────────────────


def handle_single(args):
    client = get_valyu_client()
    output_path = Path(args.output)
    work_dir = resolve_work_dir(args.output)
    mode = args.mode
    no_wait = getattr(args, "no_wait", False)
    max_cost = getattr(args, "max_cost", None)
    main_topic = getattr(args, "main_topic", None)

    query = args.query
    if main_topic:
        gate_scope([{"query": query}], {"main_topic": main_topic},
                   allow_drift=getattr(args, "allow_drift", False))
        if not getattr(args, "no_anchor", False):
            query = anchor_query(query, main_topic)

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
        state_path = append_state(work_dir, {
            "kind": "task",
            "task_id": task.deepresearch_id,
            "query": query,
            "main_topic": main_topic,
            "mode": mode,
            "output": str(output_path),
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        })
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
    purge_tmp(work_dir, "task_id", task.deepresearch_id)


def handle_batch(args):
    client = get_valyu_client()
    queries_file = Path(args.queries_file)
    output_dir = Path(args.output_dir)
    name = args.name
    mode = args.mode
    no_wait = getattr(args, "no_wait", False)
    max_cost = getattr(args, "max_cost", None)

    meta, entries = load_scoped_queries(queries_file)
    if not entries:
        print("Error: No valid queries found to research.", file=sys.stderr)
        sys.exit(1)

    check_query_limit(len(entries), args.max_queries)
    gate_scope(entries, meta, allow_drift=getattr(args, "allow_drift", False))
    check_cost_limit(mode, max_cost, task_count=len(entries))

    main_topic = meta.get("main_topic", "")
    anchoring = bool(main_topic) and not getattr(args, "no_anchor", False)
    scope_entries = []
    queries = []
    for entry in entries:
        submitted = anchor_query(entry["query"], main_topic) if anchoring else entry["query"]
        queries.append({"query": submitted})
        scope_entries.append({
            "submitted": submitted,
            "id": entry.get("id"),
            "anchor": entry.get("anchor"),
            "main_topic": main_topic,
        })
    scope = {"main_topic": main_topic, "entries": scope_entries}

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
        state_path = append_state(output_dir, {
            "kind": "batch",
            "batch_id": batch_id,
            "name": name,
            "mode": mode,
            "output_dir": str(output_dir),
            "query_count": len(queries),
            "scope": scope,
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        })
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

    _, all_succeeded = save_batch_results(client, batch_id, output_dir, scope)
    finish_batch(output_dir, batch_id, all_succeeded)
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
            scope = load_batch_scope(output_dir, batch_id)
            _, all_succeeded = save_batch_results(client, batch_id, output_dir, scope)
            finish_batch(output_dir, batch_id, all_succeeded)
        else:
            print("  Provide --output-dir to download and save results.")
    else:
        print(f"  Batch ended with status: {batch_status}")


def load_batch_scope(output_dir: Path, batch_id: str) -> dict:
    """Recover the anchor map a --no-wait batch stored at submit time."""
    state_path = tmp_state_path(output_dir)
    if not state_path.exists():
        return {}
    try:
        for entry in json.loads(state_path.read_text(encoding="utf-8")):
            if entry.get("batch_id") == batch_id:
                return entry.get("scope", {})
    except Exception:
        pass
    return {}


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

    failed = [entry for entry in manifest if entry.get("status") in ("failed", "cancelled")]

    if not failed:
        print("No failed or cancelled tasks found in manifest. Nothing to retry.")
        return

    print(f"Found {len(failed)} failed/cancelled task(s) to retry.")
    check_cost_limit(mode, max_cost, task_count=len(failed))

    # anchor_query is idempotent, so replaying an already-anchored query is safe.
    anchoring = not getattr(args, "no_anchor", False)
    scope_entries = []
    failed_queries = []
    for entry in failed:
        topic = entry.get("main_topic") or ""
        submitted = anchor_query(entry["query"], topic) if anchoring else entry["query"]
        failed_queries.append({"query": submitted})
        scope_entries.append({
            "submitted": submitted,
            "id": entry.get("id"),
            "anchor": entry.get("anchor"),
            "main_topic": topic,
        })
    scope = {"main_topic": scope_entries[0]["main_topic"] if scope_entries else "", "entries": scope_entries}

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
        state_path = append_state(output_dir, {
            "kind": "batch",
            "batch_id": batch_id,
            "name": name,
            "mode": mode,
            "output_dir": str(output_dir),
            "query_count": len(failed_queries),
            "scope": scope,
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        })
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

    retry_manifest, all_succeeded = save_batch_results(client, batch_id, output_dir, scope)

    # Merge retry results back into the original manifest
    retried = {e["query"] for e in failed}
    merged = [e for e in manifest if e["query"] not in retried]
    merged.extend(retry_manifest)
    manifest_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Merged retry results back into {manifest_path}")

    finish_batch(output_dir, batch_id, all_succeeded)
    print("Retry completed successfully!")


def handle_scope_check(args):
    """Audit finished reports for headings that wandered off the main topic."""
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"Error: Manifest file '{manifest_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error: Failed to parse manifest: {e}", file=sys.stderr)
        sys.exit(1)

    anchor_terms = []
    if args.queries_file:
        meta, _ = load_scoped_queries(Path(args.queries_file))
        anchor_terms = meta.get("anchor_terms", [])

    report_dir = Path(args.output_dir) if args.output_dir else manifest_path.parent
    flagged = 0
    checked = 0

    for entry in manifest:
        main_topic = entry.get("main_topic")
        filename = entry.get("filename")
        if not main_topic or not filename:
            continue
        report_path = report_dir / filename
        if not report_path.exists():
            continue

        checked += 1
        suspects = audit_report_scope(
            report_path.read_text(encoding="utf-8"),
            {"main_topic": main_topic, "anchor_terms": anchor_terms},
        )
        if suspects:
            flagged += 1
            print(f"  {filename}: {len(suspects)} off-topic heading(s)")
            for heading in suspects:
                print(f"    - {heading}")

    if not checked:
        print("No anchored reports found to check.")
    elif flagged:
        print(f"\nScope audit: {flagged}/{checked} report(s) contain headings unrelated to their main topic.")
    else:
        print(f"Scope audit: all {checked} report(s) stayed on topic.")


def add_scope_flags(parser):
    parser.add_argument("--no-anchor", action="store_true", help="Do not attach the main topic to submitted queries")
    parser.add_argument("--allow-drift", action="store_true", help="Downgrade scope-check errors to warnings")


def main():
    parser = argparse.ArgumentParser(
        description="Valyu DeepResearch runner: single tasks, batch research, status polling, retry, and scope audit."
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Command to run")

    # --- single: run a single deep research task ---
    parser_single = subparsers.add_parser("single", help="Run a single deep research task")
    parser_single.add_argument("--query", required=True, help="The research query to run")
    parser_single.add_argument("--output", required=True, help="Path to save the markdown report")
    parser_single.add_argument("--main-topic", default=None, help="Parent topic to anchor the query to")
    parser_single.add_argument(
        "--mode", default="fast", choices=["fast", "standard", "heavy", "max"],
        help="DeepResearch mode (default: fast)",
    )
    parser_single.add_argument("--no-wait", action="store_true", help="Submit and exit without polling")
    parser_single.add_argument("--max-cost", type=float, default=3.0, help="Max allowed cost in USD (default: 3.0)")
    add_scope_flags(parser_single)

    # --- batch: run parallel batch research ---
    parser_batch = subparsers.add_parser("batch", help="Run a batch of deep research tasks")
    parser_batch.add_argument("--queries-file", required=True, help="JSON file with queries list")
    parser_batch.add_argument("--output-dir", required=True, help="Directory to save reports and manifest")
    parser_batch.add_argument("--name", default="Batch Research Task", help="Name of the batch")
    parser_batch.add_argument(
        "--mode", default="standard", choices=["fast", "standard", "heavy", "max"],
        help="DeepResearch mode (default: standard)",
    )
    parser_batch.add_argument("--no-wait", action="store_true", help="Submit and exit without polling")
    parser_batch.add_argument("--max-cost", type=float, default=3.0, help="Max allowed cost in USD (default: 3.0)")
    parser_batch.add_argument(
        "--max-queries", type=int, default=DEFAULT_MAX_QUERIES,
        help=f"Max queries allowed in the ideas file; 0 = unlimited (default: {DEFAULT_MAX_QUERIES})",
    )
    add_scope_flags(parser_batch)

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
    add_scope_flags(parser_retry)

    # --- scope-check: local audit of finished reports ---
    parser_scope = subparsers.add_parser("scope-check", help="Audit finished reports for topic drift (no API calls)")
    parser_scope.add_argument(
        "--manifest", default=str(DEFAULT_WORK_DIR / "manifest.json"),
        help=f"Manifest to audit (default: {DEFAULT_WORK_DIR / 'manifest.json'})",
    )
    parser_scope.add_argument("--output-dir", default=None, help="Directory holding the reports (default: manifest dir)")
    parser_scope.add_argument("--queries-file", default=None, help="Ideas file to read anchor_terms from")

    args = parser.parse_args()

    if args.command == "single":
        handle_single(args)
    elif args.command == "batch":
        handle_batch(args)
    elif args.command == "status":
        handle_status(args)
    elif args.command == "retry":
        handle_retry(args)
    elif args.command == "scope-check":
        handle_scope_check(args)


if __name__ == "__main__":
    main()
