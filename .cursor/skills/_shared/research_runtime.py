#!/usr/bin/env python3
"""Shared single-task runtime for fast-init and heavy-refined stages."""
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

from research_env import check_cost_limit, get_search_config
from research_scope import append_state, purge_tmp


def response_field(response: Any, name: str, default: Any = None) -> Any:
    if isinstance(response, dict):
        return response.get(name, default)
    return getattr(response, name, default)


def extract_task_id(response: Any) -> Optional[str]:
    """Normalize SDK task identifiers across object and dict responses."""
    return (
        response_field(response, "deepresearch_id")
        or response_field(response, "task_id")
        or response_field(response, "id")
    )


def _require_success(response: Any, action: str) -> None:
    success = response_field(response, "success", True)
    if success is False:
        error = response_field(response, "error", response)
        raise RuntimeError(f"{action} failed: {error}")


def _terminal_status(response: Any) -> str:
    return str(response_field(response, "status", "unknown") or "unknown")


def _save_output(response: Any, output_path: Path) -> None:
    output_text = response_field(response, "output", "")
    if not output_text:
        raise RuntimeError("Task completed without a report output.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(str(output_text), encoding="utf-8")
    print(f"Report saved to {output_path}")


def run_single_task(
    *,
    client: Any,
    query: str,
    output_path: Path,
    work_dir: Path,
    mode: str,
    no_wait: bool,
    max_cost: Optional[float],
    main_topic: Optional[str] = None,
    hitl: bool = False,
    on_interaction: Optional[Callable[[Any], dict]] = None,
    poll_interval: int = 15,
) -> str:
    """Create a task, persist async state, or wait and save its report."""
    check_cost_limit(mode, max_cost)

    kwargs: dict[str, Any] = {
        "query": query,
        "mode": mode,
        "output_formats": ["markdown"],
    }
    search_config = get_search_config()
    if search_config:
        print(f"Applying search configuration: {search_config}")
        kwargs["search"] = search_config
    if hitl:
        kwargs["hitl"] = {"plan_review": True, "source_review": True}

    print(f"Creating deep research task in '{mode}' mode...")
    print(f"Query: {query}")
    try:
        created = client.deepresearch.create(**kwargs)
    except Exception as exc:
        raise RuntimeError(f"Task creation failed: {exc}") from exc
    _require_success(created, "Task creation")

    task_id = extract_task_id(created)
    if not task_id:
        raise RuntimeError(f"Could not retrieve a task ID from response: {created}")
    print(f"Task created successfully. Task ID: {task_id}")

    state_entry = {
        "kind": "task",
        "task_id": task_id,
        "query": query,
        "main_topic": main_topic,
        "mode": mode,
        "output": str(output_path),
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    if no_wait:
        state_path = append_state(work_dir, state_entry)
        print(f"Task submitted in --no-wait mode. State saved to {state_path}.")
        return task_id

    wait_kwargs: dict[str, Any] = {
        "poll_interval": poll_interval,
        "on_progress": lambda status: print(
            f"  Status: {response_field(status, 'status', 'running')}"
        ),
    }
    if on_interaction is not None:
        wait_kwargs["on_interaction"] = on_interaction

    print("Waiting for completion...")
    try:
        result = client.deepresearch.wait(task_id, **wait_kwargs)
    except Exception as exc:
        raise RuntimeError(f"Task wait failed: {exc}") from exc
    _require_success(result, "Task wait")

    status = _terminal_status(result)
    if status != "completed":
        error = response_field(result, "error", "No error message provided")
        raise RuntimeError(f"Task failed with status '{status}': {error}")

    cost = float(response_field(result, "cost", 0.0) or 0.0)
    print(f"Task completed successfully. Cost: ${cost:.2f}")
    _save_output(result, output_path)
    purge_tmp(work_dir, "task_id", task_id)
    return task_id


def collect_single_task(
    *,
    client: Any,
    task_id: str,
    output_path: Optional[Path],
    work_dir: Path,
    on_awaiting_input: Optional[Callable[[Any], None]] = None,
) -> str:
    """Check one task and save output when complete."""
    print(f"Checking status of task: {task_id}")
    try:
        response = client.deepresearch.status(task_id)
    except Exception as exc:
        raise RuntimeError(f"Task status failed: {exc}") from exc
    _require_success(response, "Task status")

    status = _terminal_status(response)
    print(f"  Status: {status}")
    if response_field(response, "unreachable", False):
        raise RuntimeError("Task status is temporarily unreachable; retry later.")
    if status in {"queued", "running", "in_progress", "processing", "paused"}:
        print("  Task is still in progress. Check back later.")
        return status
    if status == "awaiting_input":
        if on_awaiting_input is not None:
            on_awaiting_input(response)
        else:
            print("  Task is awaiting human input.")
        return status
    if status in {"failed", "cancelled"}:
        error = response_field(response, "error", "No error message provided")
        raise RuntimeError(f"Task ended with status '{status}': {error}")
    if status != "completed":
        raise RuntimeError(f"Unrecognized task status: {status}")

    cost = float(response_field(response, "cost", 0.0) or 0.0)
    print(f"  Task completed! Cost: ${cost:.2f}")
    if output_path is None:
        print("  Provide an output path to download and save the report.")
        return status

    _save_output(response, output_path)
    purge_tmp(work_dir, "task_id", task_id)
    print("  Temp state cleaned up.")
    return status


def exit_on_runtime_error(action: Callable[[], Any]) -> Any:
    """Convert normalized runtime failures into CLI exit behavior."""
    try:
        return action()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
