#!/usr/bin/env python3
import sys
import json
import time
import argparse
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
from research_env import (  # noqa: E402
    get_valyu_client,
    resolve_work_dir as _resolve_work_dir,
)
from research_runtime import (  # noqa: E402
    collect_single_task,
    exit_on_runtime_error,
    response_field,
    run_single_task,
)
from research_scope import (  # noqa: E402
    TMP_CHECKPOINT_NAME,
    TMP_CHECKPOINT_RESPONSE_NAME,
    anchor_query,
    audit_enrichment,
    gate_scope,
)

DEFAULT_WORK_DIR = Path("work/deep")


def resolve_work_dir(output: Optional[str]) -> Path:
    return _resolve_work_dir(output, DEFAULT_WORK_DIR)


def make_hitl_handler(work_dir: Path):
    """Return a fail-closed synchronous HITL callback."""
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

        print(f"\n[CHECKPOINT] Task paused: {checkpoint_data['type']}")
        print(f"  Details written to {checkpoint_path}")
        print(f"  Write your response to {response_path} to resume.")
        print("  Waiting for response...")

        last_invalid = None
        while True:
            if not response_path.exists():
                time.sleep(2)
                continue
            raw = response_path.read_text(encoding="utf-8")
            try:
                response_data = json.loads(raw)
                if not isinstance(response_data, dict):
                    raise ValueError("response must be a JSON object")
            except Exception as exc:
                if raw != last_invalid:
                    print(
                        f"  Invalid checkpoint response ({exc}). "
                        "Replace it with valid JSON; the task remains paused.",
                        file=sys.stderr,
                    )
                    last_invalid = raw
                time.sleep(2)
                continue
            checkpoint_path.unlink(missing_ok=True)
            response_path.unlink(missing_ok=True)
            return response_data

    return handle_interaction


def handle_research(args):
    client = get_valyu_client()
    query = args.query
    output_path = Path(args.output)
    work_dir = resolve_work_dir(args.output)
    hitl_enabled = getattr(args, "hitl", False)
    main_topic = getattr(args, "main_topic", None)

    if main_topic:
        gate_scope([{"query": query}], {"main_topic": main_topic},
                   allow_drift=getattr(args, "allow_drift", False),
                   full_scope=True)
        if not getattr(args, "no_anchor", False):
            query = anchor_query(query, main_topic)

    if hitl_enabled:
        print("HITL checkpoints enabled: plan_review, source_review")

    exit_on_runtime_error(lambda: run_single_task(
        client=client,
        query=query,
        output_path=output_path,
        work_dir=work_dir,
        mode=args.mode,
        no_wait=getattr(args, "no_wait", False),
        max_cost=getattr(args, "max_cost", None),
        main_topic=main_topic,
        hitl=hitl_enabled,
        on_interaction=make_hitl_handler(work_dir) if hitl_enabled else None,
    ))


def _save_awaiting_checkpoint(work_dir: Path, status_response) -> None:
    interaction = response_field(status_response, "interaction")
    print("  Task is awaiting human input (HITL checkpoint).")
    if not interaction:
        return
    checkpoint_path = work_dir / TMP_CHECKPOINT_NAME
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_data = {
        "interaction_id": response_field(interaction, "interaction_id"),
        "type": response_field(interaction, "type", "unknown"),
        "data": response_field(interaction, "data", {}),
    }
    checkpoint_path.write_text(
        json.dumps(checkpoint_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  Checkpoint details saved to {checkpoint_path}")


def handle_status(args):
    """Check the status of a previously submitted task and download if complete."""
    client = get_valyu_client()
    output_path = Path(args.output) if args.output else None
    work_dir = resolve_work_dir(args.output)
    exit_on_runtime_error(lambda: collect_single_task(
        client=client,
        task_id=args.task_id,
        output_path=output_path,
        work_dir=work_dir,
        on_awaiting_input=lambda response: _save_awaiting_checkpoint(work_dir, response),
    ))


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


def report_title(report_text: str) -> str:
    """First H1 of a report, used as the topic when --main-topic is omitted."""
    for line in report_text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def handle_enrich_check(args):
    """Audit whether the heavy report enriched its baseline. Local, no API calls."""
    baseline_path = Path(args.baseline)
    deep_path = Path(args.deep)

    for path in (baseline_path, deep_path):
        if not path.exists():
            print(f"Error: '{path}' does not exist.", file=sys.stderr)
            sys.exit(1)

    baseline_text = baseline_path.read_text(encoding="utf-8")
    deep_text = deep_path.read_text(encoding="utf-8")
    main_topic = args.main_topic or report_title(baseline_text)

    result = audit_enrichment(baseline_text, deep_text, {"main_topic": main_topic})
    print(f"Topic: {main_topic or '(unknown)'}")
    print(f"Baseline facets: {result['baseline_total']}  |  Heavy sections: {result['deep_total']}")

    if result["enriched"]:
        print(f"\nEnriched ({len(result['enriched'])}):")
        for heading, hits in result["enriched"]:
            print(f"  {heading}")
            for hit in hits:
                print(f"    -> {hit}")

    patterns = [p.lower() for p in (args.allow_drop or [])]
    by_design, regressions = [], []
    for heading in result["dropped"]:
        target = by_design if any(p in heading.lower() for p in patterns) else regressions
        target.append(heading)

    if by_design:
        print(f"\nDropped by design ({len(by_design)}) — outside the declared emphasis:")
        for heading in by_design:
            print(f"  {heading}")

    if regressions:
        print(f"\nNot carried over ({len(regressions)}) — regression, the heavy run lost these:")
        for heading in regressions:
            print(f"  {heading}")

    off_topic = [h for h, on_topic in result["added"] if not on_topic]
    on_topic = [h for h, on_topic in result["added"] if on_topic]

    if on_topic:
        print(f"\nNew in heavy, on topic ({len(on_topic)}):")
        for heading in on_topic:
            print(f"  {heading}")

    if off_topic:
        print(f"\nNew in heavy, off topic ({len(off_topic)}) — drift, no baseline home and no topic terminology:")
        for heading in off_topic:
            print(f"  {heading}")

    if not regressions and not off_topic:
        kept = " (ignoring facets dropped by design)" if by_design else ""
        print(f"\nEnrichment audit passed: every baseline facet came back, nothing drifted{kept}.")


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
        help="Baseline topic the query must cover in full (omit for the baseline run)",
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
        help="Downgrade scope-check errors to warnings (also permits a deliberately narrow query)",
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

    # --- enrich-check: local audit of heavy vs baseline ---
    parser_enrich = subparsers.add_parser(
        "enrich-check",
        help="Audit whether the heavy report enriched the baseline (no API calls)",
    )
    parser_enrich.add_argument(
        "--baseline", default=str(DEFAULT_WORK_DIR / "research_init.md"),
        help="Baseline report path (default: work/deep/research_init.md)",
    )
    parser_enrich.add_argument(
        "--deep", default=str(DEFAULT_WORK_DIR / "research_deep.md"),
        help="Heavy report path (default: work/deep/research_deep.md)",
    )
    parser_enrich.add_argument(
        "--main-topic", default=None,
        help="Topic to judge drift against (default: the baseline report's title)",
    )
    parser_enrich.add_argument(
        "--allow-drop", action="append", default=None, metavar="SUBSTRING",
        help="Baseline facet deliberately left out (case-insensitive substring; repeatable)",
    )

    args = parser.parse_args()

    if args.command == "run":
        handle_research(args)
    elif args.command == "status":
        handle_status(args)
    elif args.command == "respond":
        handle_respond(args)
    elif args.command == "enrich-check":
        handle_enrich_check(args)


if __name__ == "__main__":
    main()
