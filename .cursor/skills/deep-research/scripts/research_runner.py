#!/usr/bin/env python3
import os
import sys
import json
import time
import argparse
import configparser
from pathlib import Path
from typing import Any, Optional
from dotenv import load_dotenv
from valyu import Valyu

MODE_COSTS = {"fast": 0.10, "standard": 0.50, "heavy": 2.50, "max": 15.00}
STATE_FILE = "output/active_tasks.json"
CHECKPOINT_FILE = "output/checkpoint.json"
CHECKPOINT_RESPONSE_FILE = "output/checkpoint_response.json"


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


def save_active_task(task_id: str, query: str, mode: str, output: str):
    """Persist task metadata so `status` can retrieve it later."""
    state_path = Path(STATE_FILE)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    tasks = []
    if state_path.exists():
        try:
            tasks = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            tasks = []

    tasks.append({
        "task_id": task_id,
        "query": query,
        "mode": mode,
        "output": output,
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    })
    state_path.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")


def make_hitl_handler():
    """
    Returns an on_interaction callback that writes checkpoint data to a file,
    waits for a human response file, then returns it to the SDK.
    """
    def handle_interaction(interaction):
        checkpoint_path = Path(CHECKPOINT_FILE)
        response_path = Path(CHECKPOINT_RESPONSE_FILE)
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
        print(f"  Details written to {CHECKPOINT_FILE}")
        print(f"  Write your response to {CHECKPOINT_RESPONSE_FILE} to resume.")
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
    mode = args.mode
    no_wait = getattr(args, "no_wait", False)
    max_cost = getattr(args, "max_cost", None)
    hitl_enabled = getattr(args, "hitl", False)

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
        save_active_task(deepresearch_id, query, mode, str(output_path))
        print(f"Task submitted in --no-wait mode. State saved to {STATE_FILE}.")
        print("Use the 'status' command to check progress and download results later.")
        return

    print("Waiting for completion...")

    wait_kwargs: dict[str, Any] = {
        "poll_interval": 15,
        "on_progress": lambda s: print(f"  Status: {getattr(s, 'status', 'running')}"),
    }
    if hitl_enabled:
        wait_kwargs["on_interaction"] = make_hitl_handler()

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


def handle_status(args):
    """Check the status of a previously submitted task and download if complete."""
    client = get_valyu_client()
    task_id = args.task_id
    output_path = Path(args.output) if args.output else None

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
            checkpoint_path = Path(CHECKPOINT_FILE)
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_data = {
                "interaction_id": getattr(interaction, "interaction_id", None),
                "type": getattr(interaction, "type", "unknown"),
                "data": getattr(interaction, "data", {}),
            }
            checkpoint_path.write_text(json.dumps(checkpoint_data, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  Checkpoint details saved to {CHECKPOINT_FILE}")
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

            _remove_from_active(task_id)
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

    interaction_id = response_data.pop("interaction_id", None)
    if not interaction_id:
        checkpoint_path = Path(CHECKPOINT_FILE)
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
    Path(CHECKPOINT_FILE).unlink(missing_ok=True)


def _remove_from_active(task_id: str):
    state_path = Path(STATE_FILE)
    if not state_path.exists():
        return
    try:
        tasks = json.loads(state_path.read_text(encoding="utf-8"))
        tasks = [t for t in tasks if t.get("task_id") != task_id]
        state_path.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


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
