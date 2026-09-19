#!/usr/bin/env python3
"""Shared scope anchoring and temp-state helpers for the Valyu research runners.

Follow-up queries are submitted to Valyu as standalone strings, so without an
explicit anchor a sub-query drifts into whatever topic it reads like on its own.
This module keeps the parent topic attached to every follow-up and gates obvious
drift locally, before any API spend.

Two shapes share the gate. Multi-angle follow-ups are drill-downs into one
facet, so partial overlap with the main topic is expected. A
research-single-topic heavy query is a more precise restatement of the whole
topic, so it is gated with
``full_scope=True``, where thin coverage means the query narrowed instead.
"""
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional, Union

TMP_STATE_NAME = "tmp_state.json"
TMP_CHECKPOINT_NAME = "tmp_checkpoint.json"
TMP_CHECKPOINT_RESPONSE_NAME = "tmp_checkpoint_response.json"
TMP_GLOB = "tmp_*.json"

# Headings that summarise or open-endedly extend a report. Anchoring to one of
# these licenses unlimited breadth, which is how a scan-RNN baseline ended up
# spawning vision, spiking-network, and genomics sub-reports.
INELIGIBLE_ANCHOR_PATTERNS = (
    r"^executive\s+summary",
    r"^conclusions?\b",
    r"^sources?$",
    r"^references?$",
    r"applications?",
    r"future\s+directions?",
    r"recent\s+developments?",
    r"emerging",
    r"data\s+gaps?",
    r"research\s+priorit",
)

_STOPWORDS = frozenset("""
a an and are as at be by for from how in into is it its of on or over that the
their this to via with within versus vs when where which why
analysis approach approaches comparison evidence method methods overview review
study studies survey technique techniques use using
aware based driven general specific
across advance advances consideration considerations current implication
implications insight insights key landscape perspective perspectives
""".split())

# Words that describe almost any research subject. A query sharing only these
# with the main topic is a different subject wearing familiar vocabulary — the
# "spiking neural networks" case that slipped past a scan-RNN baseline.
_GENERIC_TOKENS = frozenset("""
ai algorithm algorithms application applications architecture architectures
artificial computation computational data deep design framework frameworks
intelligence learning machine model models network networks neural performance
pipeline pipelines research system systems task tasks technology training
""".split())

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_HEADING_NUM_RE = re.compile(r"^\s*\d+(\.\d+)*[.)]?\s*")


# ──────────────────────────────────────────────────────────────────────────────
# Anchoring
# ──────────────────────────────────────────────────────────────────────────────


def anchor_query(query: str, main_topic: Optional[str]) -> str:
    """Attach the parent topic to a follow-up query.

    Kept deliberately short: Valyu queries work best under ~400 characters, so
    the clause must not crowd out the semantic payload.
    """
    query = (query or "").strip()
    main_topic = (main_topic or "").strip()
    if not main_topic:
        return query
    if main_topic.lower() in query.lower():
        return query
    return f"{query} (within the scope of {main_topic})"


def tokenize(text: str) -> set:
    """Lowercase content tokens, stopwords and very short tokens removed."""
    return {
        token
        for token in _TOKEN_RE.findall((text or "").lower())
        if len(token) > 2 and token not in _STOPWORDS
    }


def normalize_heading(heading: str) -> str:
    """Strip leading numbering and surrounding markup from a heading."""
    heading = (heading or "").strip().lstrip("#").strip()
    return _HEADING_NUM_RE.sub("", heading).strip()


def is_ineligible_anchor(heading: str) -> bool:
    """True for catch-all headings that cannot constrain a drill-down."""
    normalized = normalize_heading(heading).lower()
    return any(re.search(pattern, normalized) for pattern in INELIGIBLE_ANCHOR_PATTERNS)


def scope_tokens(meta: dict) -> set:
    """Distinctive tokens of the scope, falling back to all tokens if needed."""
    tokens = tokenize(meta.get("main_topic", ""))
    for term in meta.get("anchor_terms", []):
        tokens |= tokenize(str(term))
    distinctive = tokens - _GENERIC_TOKENS
    return distinctive or tokens


# ──────────────────────────────────────────────────────────────────────────────
# Queries file
# ──────────────────────────────────────────────────────────────────────────────


def load_scoped_queries(queries_file: Union[str, Path]) -> tuple[dict, list[dict]]:
    """Parse a queries JSON file into (scope metadata, query entries).

    Accepts the anchored schema as well as the older plain list of strings.
    """
    queries_file = Path(queries_file)
    if not queries_file.exists():
        print(f"Error: Queries file '{queries_file}' does not exist.", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(queries_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error: Failed to parse queries file as JSON: {e}", file=sys.stderr)
        sys.exit(1)

    meta: dict[str, Any] = {}
    if isinstance(data, dict) and "queries" in data:
        raw = data["queries"]
        meta = {
            "main_topic": (data.get("main_topic") or "").strip(),
            "anchor_terms": [t for t in data.get("anchor_terms", []) if str(t).strip()],
            "anchor_headings": [h for h in data.get("anchor_headings", []) if str(h).strip()],
        }
    else:
        raw = data

    if not isinstance(raw, list):
        print("Error: Root or 'queries' must be a list.", file=sys.stderr)
        sys.exit(1)

    entries = []
    for item in raw:
        if isinstance(item, str):
            entries.append({"query": item})
        elif isinstance(item, dict) and "query" in item:
            entries.append({
                "query": item["query"],
                "id": item.get("id"),
                "anchor": item.get("anchor"),
                "track": item.get("track"),
            })
        else:
            print(f"Warning: Skipping invalid item: {item}", file=sys.stderr)
    return meta, entries


# ──────────────────────────────────────────────────────────────────────────────
# Drift gate
# ──────────────────────────────────────────────────────────────────────────────


def check_scope(entry: dict, meta: dict, full_scope: bool = False) -> list[tuple[str, str]]:
    """Return [(level, message)] scope problems for one query entry.

    Level is "error" (abort) or "warning" (proceed). Purely local: no API calls.

    With full_scope, the query is expected to restate the whole main topic more
    precisely rather than drill into one facet, so thin coverage of the topic's
    distinctive terms is an error instead of the goal.
    """
    issues: list[tuple[str, str]] = []
    query = entry.get("query", "")
    main_topic = meta.get("main_topic", "")
    anchor_headings = meta.get("anchor_headings", [])

    core = scope_tokens(meta)

    if core:
        overlap = tokenize(query) & core
        if not overlap:
            issues.append((
                "error",
                f"shares no distinctive terminology with the main topic ({main_topic or 'unset'}) "
                "— looks like a different subject",
            ))
        elif full_scope and len(core) >= 3 and len(overlap) * 2 < len(core):
            missing = sorted(core - overlap)
            issues.append((
                "error",
                f"covers only {len(overlap)} of {len(core)} distinctive main-topic terms "
                f"(missing: {', '.join(missing)}) — a refined restatement must keep the whole "
                "topic, not narrow to one facet (that is research-multi-angle's job)",
            ))
        elif not full_scope and len(overlap) == 1 and len(core) >= 3:
            issues.append((
                "warning",
                f"only overlaps the main topic on '{sorted(overlap)[0]}' — confirm it is a drill-down",
            ))

    anchor = entry.get("anchor")
    if anchor_headings:
        if not anchor:
            issues.append(("warning", "no anchor heading declared"))
        else:
            known = {normalize_heading(h).lower() for h in anchor_headings}
            if normalize_heading(anchor).lower() not in known:
                issues.append((
                    "error",
                    f"anchor '{anchor}' is not one of the declared anchor headings",
                ))
            elif is_ineligible_anchor(anchor):
                issues.append((
                    "error",
                    f"anchor '{anchor}' is a catch-all heading and cannot constrain scope",
                ))
    elif anchor and is_ineligible_anchor(anchor):
        issues.append((
            "error",
            f"anchor '{anchor}' is a catch-all heading and cannot constrain scope",
        ))

    return issues


def gate_scope(entries: list[dict], meta: dict, allow_drift: bool = False,
               full_scope: bool = False) -> None:
    """Report scope problems across all entries; abort on errors unless allowed."""
    if not meta.get("main_topic"):
        print("Warning: No 'main_topic' in queries file — submitting unanchored queries.", file=sys.stderr)
        return

    errors = 0
    for index, entry in enumerate(entries, start=1):
        label = entry.get("id") or f"query {index}"
        for level, message in check_scope(entry, meta, full_scope=full_scope):
            if level == "error":
                errors += 1
            print(f"  [{level}] {label}: {message}", file=sys.stderr)

    if not errors:
        shape = "covering the full scope of" if full_scope else "anchored to"
        print(f"Scope check passed: {len(entries)} query(s) {shape} '{meta['main_topic']}'.")
        return

    if allow_drift:
        print(f"Warning: {errors} scope error(s) overridden by --allow-drift.", file=sys.stderr)
        return

    fix = "Restate them over the full main topic" if full_scope else "Re-anchor them to the main topic"
    print(
        f"Error: {errors} query(s) failed the scope check. "
        f"{fix}, or pass --allow-drift to override. Aborting.",
        file=sys.stderr,
    )
    sys.exit(1)


def report_headings(report_text: str, level: int = 2) -> list[str]:
    """Substantive headings of a report at the given level, catch-alls removed."""
    prefix = "#" * level + " "
    headings = []
    for line in report_text.splitlines():
        if not line.startswith(prefix):
            continue
        heading = line[len(prefix):].strip()
        if heading and not is_ineligible_anchor(heading):
            headings.append(heading)
    return headings


def _heading_tokens(heading: str) -> set:
    """Distinctive tokens of a heading, falling back to all tokens if needed."""
    tokens = tokenize(normalize_heading(heading))
    distinctive = tokens - _GENERIC_TOKENS
    return distinctive or tokens


def audit_enrichment(baseline_text: str, deep_text: str, meta: dict) -> dict:
    """Compare a heavy report against the baseline it was meant to enrich.

    A heavy run is supposed to return every baseline facet in stronger form, so
    a baseline heading with no counterpart is a regression, not a saving.
    Headings are matched on distinctive token overlap, so rewording still counts
    as carried over. Local and free: no API calls.
    """
    baseline = report_headings(baseline_text)
    deep = report_headings(deep_text)
    core = scope_tokens(meta)

    enriched: list[tuple[str, list[str]]] = []
    dropped: list[str] = []
    added: list[tuple[str, bool]] = []
    matched: set[str] = set()

    for heading in baseline:
        tokens = _heading_tokens(heading)
        hits = [d for d in deep if tokens & _heading_tokens(d)]
        if hits:
            enriched.append((heading, hits))
            matched.update(hits)
        else:
            dropped.append(heading)

    for heading in deep:
        if heading in matched:
            continue
        on_topic = bool(core) and bool(_heading_tokens(heading) & core)
        added.append((heading, on_topic))

    return {
        "enriched": enriched,
        "dropped": dropped,
        "added": added,
        "baseline_total": len(baseline),
        "deep_total": len(deep),
    }


def audit_report_scope(report_text: str, meta: dict) -> list[str]:
    """Return H2 headings of a finished report that share no scope terminology."""
    core = scope_tokens(meta)
    if not core:
        return []

    suspects = []
    for line in report_text.splitlines():
        if not line.startswith("## "):
            continue
        heading = line[3:].strip()
        if is_ineligible_anchor(heading):
            continue
        if not tokenize(heading) & core:
            suspects.append(heading)
    return suspects


# ──────────────────────────────────────────────────────────────────────────────
# Temp state
# ──────────────────────────────────────────────────────────────────────────────


def tmp_state_path(work_dir: Union[str, Path]) -> Path:
    return Path(work_dir) / TMP_STATE_NAME


def append_state(work_dir: Union[str, Path], entry: dict) -> Path:
    """Append an async task/batch entry to the work directory's temp state."""
    state_path = tmp_state_path(work_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    entries = _read_state(state_path)
    entries.append(entry)
    state_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    return state_path


def drop_state_entry(work_dir: Union[str, Path], key: str, value: str) -> None:
    """Remove matching entries; unlink the state file once it is empty."""
    state_path = tmp_state_path(work_dir)
    if not state_path.exists():
        return
    entries = [e for e in _read_state(state_path) if e.get(key) != value]
    if entries:
        state_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        state_path.unlink(missing_ok=True)


def purge_tmp(work_dir: Union[str, Path], key: Optional[str] = None, value: Optional[str] = None) -> None:
    """Clear temp artifacts after a run finishes cleanly.

    Only called on terminal success: a batch that ends with failures keeps its
    state so `retry` can still pick it up.
    """
    work_dir = Path(work_dir)
    if key and value:
        drop_state_entry(work_dir, key, value)
    for name in (TMP_CHECKPOINT_NAME, TMP_CHECKPOINT_RESPONSE_NAME):
        (work_dir / name).unlink(missing_ok=True)


def _read_state(state_path: Path) -> list[dict]:
    try:
        entries = json.loads(state_path.read_text(encoding="utf-8"))
        return entries if isinstance(entries, list) else []
    except Exception:
        return []
