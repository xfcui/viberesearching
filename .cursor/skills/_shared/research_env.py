#!/usr/bin/env python3
"""Shared environment, client, and cost-guard helpers for the research runners.

Every runner needs the same three things before it can do any work: find the
`.env`, read one INI section out of it, and refuse to spend more than the
caller allowed. Keeping one copy here means a fix to key loading or the cost
table reaches all of them at once.
"""
import configparser
import os
import sys
from pathlib import Path
from typing import Any, Optional, Union

from dotenv import load_dotenv

MODE_COSTS = {"fast": 0.10, "standard": 0.50, "heavy": 2.50, "max": 15.00}
DEFAULT_MODE_COST = 0.50


# ──────────────────────────────────────────────────────────────────────────────
# Environment
# ──────────────────────────────────────────────────────────────────────────────


def find_env_file() -> Path:
    """Nearest `.env` walking up from this file, falling back to the cwd."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        env_file = parent / ".env"
        if env_file.exists():
            return env_file
    return Path.cwd() / ".env"


def read_ini_section(env_path: Path, section_name: str) -> dict[str, str]:
    """Read one INI section from a `.env` that mixes dotenv lines and sections."""
    if not env_path.exists():
        return {}
    try:
        text = env_path.read_text(encoding="utf-8")
        start = text.find(f"[{section_name}]")
        if start == -1:
            return {}
        parser = configparser.ConfigParser()
        parser.read_string(text[start:])
        if not parser.has_section(section_name):
            return {}
        return {key: value for key, value in parser.items(section_name) if key != "DEFAULT"}
    except Exception:
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# Valyu client
# ──────────────────────────────────────────────────────────────────────────────


def get_valyu_client():
    """Valyu client from `VALYU_API_KEY` or the `[valyu]` section. Never hardcoded."""
    # Imported here so verify-references can reuse the env helpers above without
    # requiring the Valyu SDK.
    from valyu import Valyu

    env_path = find_env_file()
    load_dotenv(env_path)
    section = read_ini_section(env_path, "valyu")
    api_key = os.getenv("VALYU_API_KEY") or section.get("api_key", "").strip()
    if not api_key:
        print("Error: VALYU_API_KEY not found in environment or [valyu] section of .env.", file=sys.stderr)
        sys.exit(1)
    return Valyu(api_key=api_key)


def get_search_config() -> Optional[dict[str, Any]]:
    """Optional `search.category` from `VALYU_CATEGORIES` / `[valyu] categories`."""
    env_path = find_env_file()
    load_dotenv(env_path)
    section = read_ini_section(env_path, "valyu")
    categories = os.getenv("VALYU_CATEGORIES") or section.get("categories")
    if categories:
        parts = [part.strip() for part in categories.strip().split(",") if part.strip()]
        if parts:
            return {"category": parts[0]}
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Guardrails
# ──────────────────────────────────────────────────────────────────────────────


def check_cost_limit(mode: str, max_cost: Optional[float], task_count: int = 1) -> None:
    """Abort if estimated cost exceeds the --max-cost safety limit."""
    if max_cost is None:
        return
    unit = MODE_COSTS.get(mode, DEFAULT_MODE_COST)
    estimated = unit * task_count
    if estimated > max_cost:
        print(
            f"Error: Estimated cost ${estimated:.2f} ({task_count} task(s) x ${unit:.2f}/{mode}) "
            f"exceeds --max-cost limit of ${max_cost:.2f}. Aborting.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"Cost check passed: estimated ${estimated:.2f} <= limit ${max_cost:.2f}")


def resolve_work_dir(output: Optional[Union[str, Path]], default: Path) -> Path:
    """Artifacts live beside the report; fall back to the skill's own directory."""
    if output:
        parent = Path(output).parent
        if str(parent) not in ("", "."):
            return parent
    return default
