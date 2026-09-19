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
    TMP_CHECKPOINT_NAME,
    TMP_CHECKPOINT_RESPONSE_NAME,
    anchor_query,
    append_state,
    gate_scope,
    purge_tmp,
)

DEFAULT_WORK_DIR = Path("work/deep")


def resolve_work_dir(output: Optional[str]) -> Path:
    return _resolve_work_dir(output, DEFAULT_WORK_DIR)


def make_hitl_handler(work_dir: Path):
    """
    Returns an on_interaction callback that writes checkpoint data to a file,
    waits for a human response file, then returns it to the SDK.
    """
    def handle_interaction(interaction):
        checkpoint_path = work_dir / TMP_CHECKPOINT_NAME
        response_path = work_dir / TMP_CHECKPOINT_RESPONSE_NAME
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

        checkpoint_data = {
            "interaction_id": getattr(interaction, "interaction_id", None),
            "type": getattr(interaction, "type", "unknown"),
            "data": getattr(interaction, "data", {}),
        }
        checkpoint_path.write_text(json.dumps(checkpoint_data, indent=2, ensure_ascii=False), encoding="utf-8")

        if response_path.exists():
            response_path.unlink()

        print(f"\n[CHECKPOINT] Task paused: {checkpoint_data['type']}")
        print(f"  Details written to {checkpoint_path}")
        print(f"  Write your response to {response_path} to resume.")
        print("  Waiting for response...")

        while not response_path.exists():
            time.sleep(2)

        try:
            response_data = json.loads(response_path.read_text(encoding="utf-8"))
            checkpoint_path.unlink(missing_ok=True)
            response_path.unlink(missing_ok=True)
            return response_data
        except Exception as e:
            print(f"  Warning: Failed to parse checkpoint response ({e}), auto-approving.", file=sys.stderr)
            checkpoint_path.unlink(missing_ok=True)
            response_path.unlink(missing_ok=True)
            return {"approved": True}

    return handle_interaction


def handle_research(args):
    client = get_valyu_client()
    query = args.query
    output_path = Path(args.output)
    work_dir = resolve_work_dir(args.output)
    mode = args.mode
    no_wait = getattr(args, "no_wait", False)
    max_cost = getattr(args, "max_cost", None)
    hitl_enabled = getattr(args, "hitl", False)
    main_topic = getattr(args, "main_topic", None)

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

    if hitl_enabled:
        kwargs["hitl"] = {"plan_review": True, "source_review": True}
        print("HITL checkpoints enabled: plan_review, source_review")

    task = client.deepresearch.create(**kwargs)

    if not getattr(task, "success", True) and not getattr(task, "deepresearch_id", None):
        print(f"Error: Failed to create task. Response: {task}", file=sys.stderr)
        sys.exit(1)

    deepresearch_id = getattr(task, "deepresearch_id", None)
    if not deepresearch_id:
        if isinstance(task, dict):
            deepresearch_id = task.get("deepresearch_id")
        else:
            deepresearch_id = getattr(task, "id", None)

    if not deepresearch_id:
        print(f"Error: Could not retrieve deepresearch_id from response: {task}", file=sys.stderr)
        sys.exit(1)

    print(f"Task created successfully. Task ID: {deepresearch_id}")

    if no_wait:
        state_path = append_state(work_dir, {
            "kind": "task",
            "task_id": deepresearch_id,
            "query": query,
            "main_topic": main_topic,
            "mode": mode,
            "output": str(output_path),
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        })
        print(f"Task submitted in --no-wait mode. State saved to {state_path}.")
        print("Use the 'status' command to check progress and download results later.")
        return

    print("Waiting for completion...")

    wait_kwargs: dict[str, Any] = {
        "poll_interval": 15,
        "on_progress": lambda s: print(f"  Status: {getattr(s, 'status', 'running')}"),
    }
    if hitl_enabled:
        wait_kwargs["on_interaction"] = make_hitl_handler(work_dir)

    result = client.deepresearch.wait(deepresearch_id, **wait_kwargs)

    status = getattr(result, "status", "unknown")
    if status != "completed":
        error_detail = getattr(result, "error", "No error message provided")
        print(f"Error: Task failed with status '{status}'. Details: {error_detail}", file=sys.stderr)
        sys.exit(1)

    print("Task completed successfully!")
    cost = getattr(result, "cost", 0.0)
    print(f"Report cost: ${cost:.2f}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_text = getattr(result, "output", "") or "No output generated."
    output_path.write_text(output_text, encoding="utf-8")
    print(f"Report saved to {output_path}")
    purge_tmp(work_dir, "task_id", deepresearch_id)


def handle_status(args):
    """Check the status of a previously submitted task and download if complete."""
    client = get_valyu_client()
    task_id = args.task_id
    output_path = Path(args.output) if args.output else None
    work_dir = resolve_work_dir(args.output)

    print(f"Checking status of task: {task_id}")
    status_resp = client.deepresearch.status(task_id)

    task_status = getattr(status_resp, "status", "unknown")
    print(f"  Status: {task_status}")

    if task_status in ("queued", "running"):
        print("  Task is still in progress. Check back later.")
        return

    if task_status == "awaiting_input":
        interaction = getattr(status_resp, "interaction", None)
        print("  Task is awaiting human input (HITL checkpoint).")
        if interaction:
            checkpoint_path = work_dir / TMP_CHECKPOINT_NAME
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_data = {
                "interaction_id": getattr(interaction, "interaction_id", None),
                "type": getattr(interaction, "type", "unknown"),
                "data": getattr(interaction, "data", {}),
            }
            checkpoint_path.write_text(json.dumps(checkpoint_data, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  Checkpoint details saved to {checkpoint_path}")
        return

    if task_status == "failed":
        error_detail = getattr(status_resp, "error", "No error message provided")
        print(f"  Task failed. Error: {error_detail}", file=sys.stderr)
        sys.exit(1)

    if task_status == "completed":
        cost = getattr(status_resp, "cost", 0.0)
        print(f"  Task completed! Cost: ${cost:.2f}")

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_text = getattr(status_resp, "output", "") or "No output generated."
            output_path.write_text(output_text, encoding="utf-8")
            print(f"  Report saved to {output_path}")

            purge_tmp(work_dir, "task_id", task_id)
            print("  Temp state cleaned up.")
        else:
            print("  Provide --output to download and save the report.")
    else:
        print(f"  Unrecognized status: {task_status}")


def handle_respond(args):
    """Respond to a HITL checkpoint for a paused/awaiting_input task."""
    client = get_valyu_client()
    task_id = args.task_id
    response_file = Path(args.response_file)

    if not response_file.exists():
        print(f"Error: Response file '{response_file}' does not exist.", file=sys.stderr)
        sys.exit(1)

    try:
        response_data = json.loads(response_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error: Failed to parse response file: {e}", file=sys.stderr)
        sys.exit(1)

    checkpoint_path = resolve_work_dir(str(response_file)) / TMP_CHECKPOINT_NAME

    interaction_id = response_data.pop("interaction_id", None)
    if not interaction_id:
        if checkpoint_path.exists():
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            interaction_id = checkpoint.get("interaction_id")

    if not interaction_id:
        print("Error: No interaction_id found in response file or checkpoint file.", file=sys.stderr)
        sys.exit(1)

    print(f"Responding to checkpoint {interaction_id} for task {task_id}...")
    result = client.deepresearch.respond(
        task_id=task_id,
        interaction_id=interaction_id,
        response=response_data,
    )
    print(f"  Response accepted. Task status: {getattr(result, 'status', 'resumed')}")
    checkpoint_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description="Valyu DeepResearch runner: create, poll, and manage single research tasks."
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Command to run")

    # --- run: create and optionally wait for a research task ---
    parser_run = subparsers.add_parser("run", help="Create a new deep research task")
    parser_run.add_argument("--query", required=True, help="The research query")
    parser_run.add_argument("--output", required=True, help="Path to save the markdown report")
    parser_run.add_argument(
        "--main-topic", default=None,
        help="Parent topic to anchor the query to (omit for the baseline run)",
    )
    parser_run.add_argument(
        "--mode", default="fast", choices=["fast", "standard", "heavy", "max"],
        help="DeepResearch mode (default: fast)",
    )
    parser_run.add_argument(
        "--no-wait", action="store_true",
        help="Submit task and exit immediately without polling for results",
    )
    parser_run.add_argument(
        "--max-cost", type=float, default=3.0,
        help="Maximum allowed estimated cost in USD. Aborts if exceeded. (default: 3.0)",
    )
    parser_run.add_argument(
        "--hitl", action="store_true",
        help="Enable human-in-the-loop checkpoints (plan_review, source_review)",
    )
    parser_run.add_argument(
        "--no-anchor", action="store_true",
        help="Do not attach the main topic to the submitted query",
    )
    parser_run.add_argument(
        "--allow-drift", action="store_true",
        help="Downgrade scope-check errors to warnings",
    )

    # --- status: check task progress and optionally download ---
    parser_status = subparsers.add_parser("status", help="Check status of a submitted task")
    parser_status.add_argument("--task-id", required=True, help="The deepresearch task ID")
    parser_status.add_argument("--output", default=None, help="Path to save report if completed")

    # --- respond: reply to a HITL checkpoint ---
    parser_respond = subparsers.add_parser("respond", help="Respond to a HITL checkpoint")
    parser_respond.add_argument("--task-id", required=True, help="The deepresearch task ID")
    parser_respond.add_argument(
        "--response-file", required=True,
        help="JSON file containing the checkpoint response",
    )

    args = parser.parse_args()

    if args.command == "run":
        handle_research(args)
    elif args.command == "status":
        handle_status(args)
    elif args.command == "respond":
        handle_respond(args)


if __name__ == "__main__":
    main()
