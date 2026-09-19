#!/usr/bin/env python3
"""Verify and enrich research report references via the OpenAlex API."""

from __future__ import annotations

import argparse
import difflib
import glob
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
from research_env import find_env_file, read_ini_section  # noqa: E402

OPENALEX_BASE = "https://api.openalex.org"
CACHE_FILE_NAME = "openalex_cache.json"
CACHE_AUTO = "auto"
CACHE_VERSION = 2
CACHE_FLUSH_EVERY = 25
DEFAULT_INPUT_GLOB = "work/**/*.md"
SELECT_FIELDS = (
    "id,doi,title,display_name,publication_year,authorships,"
    "primary_location,cited_by_count,open_access"
)
SOURCE_HEADINGS = ("sources", "references")
SOURCE_LINE_RE = re.compile(
    r"^\[(\d+)\]\s+(.+?)\s+-\s+(https?://\S+)\s*$",
    re.IGNORECASE,
)
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s?#]+", re.IGNORECASE)
PMID_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d{1,8})(?:[/?#]|$)", re.IGNORECASE)
PMCID_RE = re.compile(r"(?:/|pmc/)(PMC\d+)", re.IGNORECASE)
# New-style (2108.06036) and legacy (cs/0701001, math.GT/0309136) arXiv IDs;
# any trailing version suffix is dropped so 2108.06036v2 dedups with 2108.06036.
ARXIV_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})(?:v\d+)?",
    re.IGNORECASE,
)
BIORXIV_RE = re.compile(r"(?:biorxiv|medrxiv|chemrxiv)\.org/content/10\.1101/[^\s?#]+", re.IGNORECASE)
ARXIV_DOI_PREFIX = "10.48550/arxiv."

TITLE_TAG_RE = re.compile(
    r"^(?:\[\s*(?:arxiv:)?\d{4}\.\d{4,5}(?:v\d+)?\s*\]|\(pdf\))\s*",
    re.IGNORECASE,
)
TITLE_SITE_SUFFIX_RE = re.compile(
    r"\s+[-–—]\s+(?:pubmed(?:\s+central)?|pmc|sciencedirect|researchgate|google\s+scholar)\s*$",
    re.IGNORECASE,
)
# Characters OpenAlex reads as filter syntax inside a search value.
SEARCH_UNSAFE_RE = re.compile(r"[,|?*]")
MAX_SEARCH_TITLE_CHARS = 200

COST_SINGLETON = 0.0
COST_LIST = 0.0001
# Failures that count as "errored" in a summary, as opposed to a clean
# not_found / ambiguous verdict from OpenAlex.
ERROR_CODES = frozenset({"rate_limited", "budget_exceeded", "network_error", "bad_request", "skipped"})
# Per-report fields, never stored in the shared cache.
VOLATILE_FIELDS = frozenset({"index", "original_title", "original_url"})


class LookupAborted(Exception):
    """A lookup could not complete. `kind` is the error code recorded on the record.

    `rate_limited` and `budget_exceeded` halt the whole run; `bad_request` and
    `network_error` only fail the reference at hand.
    """

    HALTING = frozenset({"rate_limited", "budget_exceeded"})

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


@dataclass
class ParsedReference:
    index: int
    title: str
    url: str


@dataclass
class Identifier:
    type: str
    value: str


@dataclass
class RequestStats:
    live_calls: int = 0
    cache_hits: int = 0
    memo_hits: int = 0
    estimated_cost_usd: float = 0.0
    halted: bool = False
    halt_reason: Optional[str] = None


@dataclass
class VerifyConfig:
    api_key: Optional[str] = None
    mailto: Optional[str] = None
    rate: float = 5.0
    sim_threshold: float = 0.8
    max_cost: Optional[float] = None
    retries: int = 4
    backoff_base: float = 1.0
    backoff_cap: float = 30.0
    use_cache: bool = True
    refresh_cache: bool = False
    force_search: bool = False
    cache: str = CACHE_AUTO


def write_json_atomic(path: Path, payload: Any) -> None:
    """Write via a temp file so an interrupted run cannot truncate the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, path)


def load_openalex_auth() -> tuple[Optional[str], Optional[str]]:
    """Return (api_key, mailto). Both are optional: OpenAlex serves anonymous
    traffic, a `mailto` joins the polite pool, and a key raises the daily cap.
    """
    env_path = find_env_file()
    load_dotenv(env_path)
    section = read_ini_section(env_path, "openalex")
    api_key = (os.getenv("OPENALEX_API_KEY") or section.get("api_key", "")).strip() or None
    mailto = (os.getenv("OPENALEX_MAILTO") or section.get("mailto", "")).strip() or None
    if not api_key and not mailto:
        print(
            "Note: no OPENALEX_API_KEY or OPENALEX_MAILTO set — using the anonymous "
            "pool, which is rate-limited more aggressively.",
            file=sys.stderr,
        )
    return api_key, mailto


def normalize_title(title: str) -> str:
    cleaned = re.sub(r"\s+", " ", title.lower().strip())
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    return cleaned


def clean_search_title(title: str) -> str:
    """Strip scraped site chrome and filter-breaking characters from a title.

    Report titles arrive as search-result headlines: `[2512.04123] Real Title`,
    `Real Title - PubMed`, `Journal | Free Full-Text | Real Title | HTML`.

    OpenAlex rejects a `title.search` value with HTTP 400 when it contains a
    comma (filter separator), a pipe (OR), or a `?`/`*` wildcard, so those
    characters are removed rather than retried.
    """
    cleaned = re.sub(r"\s+", " ", (title or "").strip())
    cleaned = TITLE_TAG_RE.sub("", cleaned)
    if "|" in cleaned:
        cleaned = max((segment.strip() for segment in cleaned.split("|")), key=len)
    cleaned = TITLE_SITE_SUFFIX_RE.sub("", cleaned)
    cleaned = SEARCH_UNSAFE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lstrip("!-")
    return cleaned[:MAX_SEARCH_TITLE_CHARS].strip()


def normalize_doi(raw: str) -> str:
    doi = raw.strip().lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = doi.rstrip(".,;)")
    return doi


def arxiv_doi(arxiv_id: str) -> str:
    """DataCite DOI minted for every arXiv submission."""
    return f"{ARXIV_DOI_PREFIX}{arxiv_id.lower()}"


def dedup_key(identifier: Optional[Identifier], title: str) -> str:
    if identifier:
        if identifier.type == "doi":
            return f"doi:{normalize_doi(identifier.value)}"
        if identifier.type == "arxiv":
            # Same key as the DataCite DOI, so both spellings of one preprint
            # collapse into a single lookup.
            return f"doi:{arxiv_doi(identifier.value)}"
        return f"{identifier.type}:{identifier.value.lower()}"
    return f"title:{normalize_title(title)}"


def singleton_path(identifier: Identifier) -> Optional[str]:
    """OpenAlex single-work path for an identifier, or None if it has no usable one.

    PMCIDs are deliberately absent: OpenAlex indexes no `pmcid` for the PMC
    records these reports cite, so the lookup only ever spends a round trip
    before falling through to title search.
    """
    if identifier.type == "doi":
        return f"/works/doi:{identifier.value}"
    if identifier.type == "arxiv":
        return f"/works/doi:{arxiv_doi(identifier.value)}"
    if identifier.type == "pmid":
        return f"/works/pmid:{identifier.value}"
    return None


def extract_identifier(title: str, url: str) -> Optional[Identifier]:
    url_lower = url.lower()

    doi_match = DOI_RE.search(url)
    if doi_match:
        return Identifier("doi", normalize_doi(doi_match.group(0)))

    if "doi.org/" in url_lower:
        path = url.split("doi.org/", 1)[1].split("?")[0].split("#")[0]
        return Identifier("doi", normalize_doi(unquote(path)))

    biorxiv_match = BIORXIV_RE.search(url)
    if biorxiv_match:
        return Identifier("doi", normalize_doi(biorxiv_match.group(0)))

    pmc_match = PMCID_RE.search(url)
    if pmc_match:
        return Identifier("pmcid", pmc_match.group(1).upper())

    pmid_match = PMID_RE.search(url)
    if pmid_match:
        return Identifier("pmid", pmid_match.group(1))

    arxiv_match = ARXIV_RE.search(url)
    if arxiv_match:
        return Identifier("arxiv", arxiv_match.group(1))

    return None


def parse_sources_block(text: str) -> list[ParsedReference]:
    lines = text.splitlines()
    start_idx = None
    for idx, line in enumerate(lines):
        heading = line.strip().lstrip("#").strip().lower()
        if heading in SOURCE_HEADINGS:
            start_idx = idx + 1
            break

    if start_idx is None:
        return []

    refs: list[ParsedReference] = []
    for line in lines[start_idx:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            break
        match = SOURCE_LINE_RE.match(stripped)
        if match:
            refs.append(
                ParsedReference(
                    index=int(match.group(1)),
                    title=match.group(2).strip(),
                    url=match.group(3).strip(),
                )
            )
    return refs


def expand_input_paths(pattern: str) -> list[Path]:
    matches = sorted(Path(p) for p in glob.glob(pattern, recursive=True))
    if not matches:
        candidate = Path(pattern)
        if candidate.is_file():
            return [candidate]
        print(f"Warning: no files matched input pattern '{pattern}'", file=sys.stderr)
    return matches


def refs_json_path(report_path: Path) -> Path:
    return report_path.with_suffix(".json")


class OpenAlexClient:
    def __init__(self, config: VerifyConfig):
        self.config = config
        self.session = requests.Session()
        self._last_request_at = 0.0
        self.stats = RequestStats()

    def _throttle(self) -> None:
        if self.config.rate <= 0:
            return
        min_interval = 1.0 / self.config.rate
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

    def _check_cost(self, additional_cost: float) -> None:
        projected = self.stats.estimated_cost_usd + additional_cost
        if self.config.max_cost is not None and projected > self.config.max_cost:
            raise LookupAborted(
                "budget_exceeded",
                f"estimated ${projected:.4f} exceeds --max-cost ${self.config.max_cost:.4f}",
            )

    def _request_with_retry(self, url: str, params: dict[str, Any], cost: float) -> Optional[dict[str, Any]]:
        self._check_cost(cost)
        last_error: Optional[str] = None

        for attempt in range(self.config.retries + 1):
            self._throttle()
            try:
                response = self.session.get(url, params=params, timeout=30)
                self._last_request_at = time.monotonic()
            except requests.RequestException as exc:
                last_error = str(exc)
                if attempt >= self.config.retries:
                    raise LookupAborted("network_error", last_error) from exc
                self._sleep_backoff(attempt, None)
                continue

            if response.status_code == 404:
                return None

            if response.status_code == 429:
                last_error = "HTTP 429"
                if attempt >= self.config.retries:
                    raise LookupAborted("rate_limited", last_error)
                self._sleep_backoff(attempt, response.headers.get("Retry-After"))
                continue

            if response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                if attempt >= self.config.retries:
                    raise LookupAborted("network_error", last_error)
                self._sleep_backoff(attempt, response.headers.get("Retry-After"))
                continue

            if not response.ok:
                # Any other 4xx is a rejected request, not a transient fault;
                # replaying it just burns the backoff schedule.
                raise LookupAborted("bad_request", f"HTTP {response.status_code}: {response.text[:200]}")

            self.stats.live_calls += 1
            self.stats.estimated_cost_usd += cost
            return response.json()

        raise LookupAborted("network_error", last_error or "unknown error")

    def _sleep_backoff(self, attempt: int, retry_after: Optional[str]) -> None:
        if retry_after:
            try:
                time.sleep(float(retry_after))
                return
            except ValueError:
                pass
        delay = min(self.config.backoff_base * (2**attempt), self.config.backoff_cap)
        delay += random.uniform(0, 0.5)
        time.sleep(delay)

    def _base_params(self) -> dict[str, str]:
        params = {"select": SELECT_FIELDS}
        if self.config.api_key:
            params["api_key"] = self.config.api_key
        elif self.config.mailto:
            params["mailto"] = self.config.mailto
        return params

    def lookup_singleton(self, identifier: Identifier) -> tuple[Optional[dict[str, Any]], str]:
        path = singleton_path(identifier)
        if path is None:
            return None, "unsupported_identifier"

        url = f"{OPENALEX_BASE}{path}"
        result = self._request_with_retry(url, self._base_params(), COST_SINGLETON)
        if result is None:
            return None, "not_found"
        return result, "singleton"

    def search_by_title(self, title: str) -> tuple[Optional[dict[str, Any]], float, str]:
        query = clean_search_title(title)
        if not query:
            return None, 0.0, "not_found"

        params = self._base_params()
        params["filter"] = f"title.search:{query}"
        params["per-page"] = "5"
        url = f"{OPENALEX_BASE}/works"
        payload = self._request_with_retry(url, params, COST_LIST)
        if not payload:
            return None, 0.0, "not_found"
        results = payload.get("results") or []
        if not results:
            return None, 0.0, "not_found"

        # Score against the original title: the cleaned form is only a query.
        normalized = normalize_title(title)
        scored = [
            (
                difflib.SequenceMatcher(
                    None,
                    normalized,
                    normalize_title(item.get("display_name") or item.get("title") or ""),
                ).ratio(),
                item,
            )
            for item in results
        ]
        similarity, best = max(scored, key=lambda pair: pair[0])
        return best, similarity, "title_search"


class ReferenceCache:
    """Verified OpenAlex lookups, reused across runs.

    Only positives live here, so an unresolved reference is always re-queried
    by the next `verify` or `retry`.
    """

    def __init__(self, path: Path, enabled: bool = True, refresh: bool = False):
        self.path = path
        self.enabled = enabled
        self.refresh = refresh
        self.data: dict[str, Any] = {}
        self.dirty = False
        if enabled and not refresh and path.exists():
            self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        entries = raw.get("entries") if raw.get("version") else raw
        if not isinstance(entries, dict):
            return
        # Drop negatives left behind by caches written before positives-only.
        self.data = {
            key: value
            for key, value in entries.items()
            if isinstance(value, dict) and value.get("verified")
        }
        self.dirty = len(self.data) != len(entries) or not raw.get("version")

    def get(self, key: str) -> Optional[dict[str, Any]]:
        if not self.enabled or self.refresh:
            return None
        return self.data.get(key)

    def set(self, key: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        self.data[key] = value
        self.dirty = True

    def save(self) -> None:
        if not self.enabled or not self.dirty:
            return
        write_json_atomic(self.path, {"version": CACHE_VERSION, "entries": self.data})
        self.dirty = False


class CacheStore:
    """Resolves which cache file backs a given report.

    Default (`auto`) keeps one cache beside each report directory, so a project
    under `work/<topic>/<angle>/` carries its own; an explicit `--cache` path
    makes every report share a single file.
    """

    def __init__(self, cache_arg: str, enabled: bool = True, refresh: bool = False):
        self.explicit_path = None if cache_arg == CACHE_AUTO else Path(cache_arg)
        self.enabled = enabled
        self.refresh = refresh
        self._caches: dict[Path, ReferenceCache] = {}

    def for_report(self, report_path: Path) -> ReferenceCache:
        path = self.explicit_path or (report_path.parent / CACHE_FILE_NAME)
        cache = self._caches.get(path)
        if cache is None:
            cache = ReferenceCache(path, enabled=self.enabled, refresh=self.refresh)
            self._caches[path] = cache
        return cache

    def save_all(self) -> None:
        for cache in self._caches.values():
            cache.save()


def extract_authors(work: dict[str, Any]) -> list[str]:
    authors = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        name = author.get("display_name")
        if name:
            authors.append(name)
    return authors[:10]


def extract_venue(work: dict[str, Any]) -> Optional[str]:
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    return source.get("display_name")


def build_openalex_payload(work: dict[str, Any]) -> dict[str, Any]:
    open_access = work.get("open_access") or {}
    return {
        "id": work.get("id"),
        "doi": work.get("doi"),
        "title": work.get("display_name") or work.get("title"),
        "authors": extract_authors(work),
        "publication_year": work.get("publication_year"),
        "venue": extract_venue(work),
        "cited_by_count": work.get("cited_by_count"),
        "oa_status": open_access.get("oa_status"),
        "oa_url": open_access.get("oa_url"),
    }


def resolve_reference(
    client: OpenAlexClient,
    cache: ReferenceCache,
    memo: dict[str, dict[str, Any]],
    ref: ParsedReference,
    sim_threshold: float,
    force_search: bool = False,
) -> dict[str, Any]:
    identifier = extract_identifier(ref.title, ref.url)
    key = dedup_key(identifier, ref.title)
    stamp = {
        "index": ref.index,
        "original_title": ref.title,
        "original_url": ref.url,
        "identifier": {"type": identifier.type, "value": identifier.value} if identifier else None,
        "dedup_key": key,
    }

    if key in memo:
        client.stats.memo_hits += 1
        return {**memo[key], **stamp, "cache_hit": True}

    cached = cache.get(key)
    if cached:
        client.stats.cache_hits += 1
        record = {**cached, **stamp, "cache_hit": True}
        memo[key] = record
        return record

    record: dict[str, Any] = {
        **stamp,
        "verified": False,
        "error": None,
        "attempts": 1,
        "match_method": None,
        "title_similarity": None,
        "openalex": None,
        "cache_hit": False,
    }

    work: Optional[dict[str, Any]] = None
    match_method: Optional[str] = None
    similarity: Optional[float] = None

    try:
        if identifier and not force_search:
            work, match_method = client.lookup_singleton(identifier)

        if work is None:
            candidate, similarity, match_method = client.search_by_title(ref.title)
            record["title_similarity"] = round(similarity, 4)
            record["match_method"] = match_method
            if candidate and similarity >= sim_threshold:
                work = candidate
            else:
                record["error"] = "ambiguous" if candidate else "not_found"
                memo[key] = record
                return record

        record["openalex"] = build_openalex_payload(work)
        record["verified"] = True
        record["match_method"] = match_method
        if similarity is None:
            canonical = work.get("display_name") or work.get("title") or ""
            similarity = difflib.SequenceMatcher(
                None, normalize_title(ref.title), normalize_title(canonical)
            ).ratio()
        record["title_similarity"] = round(similarity, 4)

    except LookupAborted as exc:
        record["error"] = exc.kind
        record["attempts"] = client.config.retries + 1
        if exc.kind in LookupAborted.HALTING:
            client.stats.halted = True
            client.stats.halt_reason = exc.kind
        elif exc.kind == "network_error" and identifier and not force_search and work is None:
            # A singleton lookup can fail transiently; title search is a second route.
            try:
                candidate, similarity, match_method = client.search_by_title(ref.title)
                record["title_similarity"] = round(similarity, 4)
                if candidate and similarity >= sim_threshold:
                    record["openalex"] = build_openalex_payload(candidate)
                    record["verified"] = True
                    record["match_method"] = match_method
                    record["error"] = None
            except LookupAborted as fallback_exc:
                record["error"] = fallback_exc.kind
                if fallback_exc.kind in LookupAborted.HALTING:
                    client.stats.halted = True
                    client.stats.halt_reason = fallback_exc.kind

    memo[key] = record
    if record["verified"]:
        # Negative results are never persisted: caching them would make `retry`
        # a no-op, since every unresolved record would come back as a cache hit.
        cache.set(key, {k: v for k, v in record.items() if k not in VOLATILE_FIELDS})
    return record


def snapshot_stats(stats: RequestStats) -> RequestStats:
    return RequestStats(
        live_calls=stats.live_calls,
        cache_hits=stats.cache_hits,
        memo_hits=stats.memo_hits,
        estimated_cost_usd=stats.estimated_cost_usd,
    )


def stats_delta(stats: RequestStats, before: RequestStats) -> RequestStats:
    """Work done since `before`, so each sidecar reports its own counters."""
    return RequestStats(
        live_calls=stats.live_calls - before.live_calls,
        cache_hits=stats.cache_hits - before.cache_hits,
        memo_hits=stats.memo_hits - before.memo_hits,
        estimated_cost_usd=stats.estimated_cost_usd - before.estimated_cost_usd,
        halted=stats.halted,
        halt_reason=stats.halt_reason,
    )


def carry_stats(prior_summary: dict[str, Any], delta: RequestStats) -> RequestStats:
    """Add this run's work to the counters a sidecar already recorded."""

    def prior(field_name: str, default: float = 0.0) -> float:
        value = prior_summary.get(field_name, default)
        return value if isinstance(value, (int, float)) else default

    return RequestStats(
        live_calls=int(prior("live_calls")) + delta.live_calls,
        cache_hits=int(prior("cache_hits")) + delta.cache_hits,
        memo_hits=int(prior("memo_hits")) + delta.memo_hits,
        estimated_cost_usd=prior("estimated_openalex_cost_usd") + delta.estimated_cost_usd,
        halted=delta.halted,
        halt_reason=delta.halt_reason,
    )


def skipped_record(ref: ParsedReference) -> dict[str, Any]:
    """Placeholder for a reference the run never reached after halting."""
    identifier = extract_identifier(ref.title, ref.url)
    return {
        "index": ref.index,
        "original_title": ref.title,
        "original_url": ref.url,
        "identifier": {"type": identifier.type, "value": identifier.value} if identifier else None,
        "dedup_key": dedup_key(identifier, ref.title),
        "verified": False,
        "error": "skipped",
        "attempts": 0,
        "match_method": None,
        "title_similarity": None,
        "openalex": None,
        "cache_hit": False,
    }


def truncate_title(title: str, max_len: int = 55) -> str:
    cleaned = re.sub(r"\s+", " ", title.strip())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1] + "…"


def format_record_status(record: dict[str, Any]) -> str:
    if record.get("verified"):
        if record.get("cache_hit"):
            return "verified (cached)"
        method = record.get("match_method") or "verified"
        similarity = record.get("title_similarity")
        if similarity is not None and method == "title_search":
            return f"verified ({method}, sim={similarity:.2f})"
        return f"verified ({method})"
    error = record.get("error")
    if error:
        return str(error)
    return "unverified"


def print_ref_progress(
    current: int,
    total: int,
    ref: ParsedReference,
    record: dict[str, Any],
    *,
    prefix: str = "    ",
    status: Optional[str] = None,
) -> None:
    label = status or format_record_status(record)
    print(
        f"{prefix}[{current}/{total}] [{ref.index}] {truncate_title(ref.title)} -> {label}",
        flush=True,
    )


def summarize_records(report_path: Path, records: list[dict[str, Any]], stats: RequestStats) -> dict[str, Any]:
    verified = sum(1 for r in records if r.get("verified"))
    unverified = sum(1 for r in records if not r.get("verified") and not r.get("error"))
    errored = sum(1 for r in records if r.get("error") in ERROR_CODES)
    ambiguous = sum(1 for r in records if r.get("error") == "ambiguous")
    not_found = sum(1 for r in records if r.get("error") == "not_found")
    skipped = sum(1 for r in records if r.get("error") == "skipped")

    return {
        "report": str(report_path),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {
            "total": len(records),
            "verified": verified,
            "unverified": unverified,
            "errored": errored,
            "ambiguous": ambiguous,
            "not_found": not_found,
            "skipped": skipped,
            "live_calls": stats.live_calls,
            "cache_hits": stats.cache_hits,
            "memo_hits": stats.memo_hits,
            "estimated_openalex_cost_usd": round(stats.estimated_cost_usd, 6),
        },
        "references": records,
    }


def verify_report(
    report_path: Path,
    client: OpenAlexClient,
    cache: ReferenceCache,
    memo: dict[str, dict[str, Any]],
    sim_threshold: float,
    force_search: bool = False,
    *,
    refs: Optional[list[ParsedReference]] = None,
    show_progress: bool = True,
) -> dict[str, Any]:
    refs = refs if refs is not None else parse_sources_block(report_path.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    stats_before = snapshot_stats(client.stats)
    flushed_at = client.stats.live_calls

    for idx, ref in enumerate(refs, start=1):
        if client.stats.halted:
            record = skipped_record(ref)
        else:
            record = resolve_reference(client, cache, memo, ref, sim_threshold, force_search=force_search)
        records.append(record)
        if show_progress:
            print_ref_progress(idx, len(refs), ref, record)
        if client.stats.live_calls - flushed_at >= CACHE_FLUSH_EVERY:
            cache.save()
            flushed_at = client.stats.live_calls

    return summarize_records(report_path, records, stats_delta(client.stats, stats_before))


def write_refs_json(payload: dict[str, Any], output_path: Path) -> None:
    write_json_atomic(output_path, payload)


def build_config(args: argparse.Namespace) -> VerifyConfig:
    api_key, mailto = load_openalex_auth()
    return VerifyConfig(
        api_key=api_key,
        mailto=mailto,
        rate=args.rate,
        sim_threshold=args.sim_threshold,
        max_cost=args.max_cost,
        retries=args.retries,
        backoff_base=args.backoff_base,
        backoff_cap=args.backoff_cap,
        use_cache=not args.no_cache,
        refresh_cache=args.refresh_cache,
        force_search=getattr(args, "force_search", False),
        cache=args.cache,
    )


def report_halt_reason(client: OpenAlexClient) -> None:
    if not client.stats.halted:
        return
    reason = client.stats.halt_reason or "rate_limited"
    detail = (
        "estimated cost hit --max-cost"
        if reason == "budget_exceeded"
        else "OpenAlex rate limit reached"
    )
    print(f"    Stopped early: {detail}. Re-run 'retry' to finish.", file=sys.stderr)


def handle_verify(args: argparse.Namespace) -> None:
    config = build_config(args)
    client = OpenAlexClient(config)
    caches = CacheStore(config.cache, enabled=config.use_cache, refresh=config.refresh_cache)
    memo: dict[str, dict[str, Any]] = {}

    report_paths = expand_input_paths(args.input or DEFAULT_INPUT_GLOB)
    if not report_paths:
        print("No report files to verify.", file=sys.stderr)
        sys.exit(1)

    # Parse once; reports without a Sources block are not verification targets.
    parsed = [(path, parse_sources_block(path.read_text(encoding="utf-8"))) for path in report_paths]
    targets = [(path, refs) for path, refs in parsed if refs]
    without_sources = len(parsed) - len(targets)
    total_refs = sum(len(refs) for _, refs in targets)

    if not targets:
        print(f"No '## Sources' block found in {len(parsed)} matched file(s). Nothing to verify.", file=sys.stderr)
        sys.exit(1)

    print(f"Verifying references in {len(targets)} report(s) ({total_refs} reference(s) total)...")
    if without_sources:
        print(f"  Skipped {without_sources} file(s) without a '## Sources' block.")
    total_verified = 0

    for report_idx, (report_path, refs) in enumerate(targets, start=1):
        print(f"\n  Report {report_idx}/{len(targets)}: {report_path} ({len(refs)} reference(s))")
        cache = caches.for_report(report_path)
        payload = verify_report(report_path, client, cache, memo, config.sim_threshold, refs=refs)
        output_path = refs_json_path(report_path)
        write_refs_json(payload, output_path)
        summary = payload["summary"]
        total_verified += summary["verified"]
        print(
            f"    refs={summary['total']} verified={summary['verified']} "
            f"ambiguous={summary['ambiguous']} not_found={summary['not_found']} "
            f"errored={summary['errored']} -> {output_path.name}"
        )
        if client.stats.halted:
            report_halt_reason(client)
            break

    caches.save_all()
    print(
        f"\nDone. {total_verified}/{total_refs} references verified across {len(targets)} report(s). "
        f"live_calls={client.stats.live_calls} cache_hits={client.stats.cache_hits} "
        f"memo_hits={client.stats.memo_hits} est_cost=${client.stats.estimated_cost_usd:.4f}"
    )


def should_retry_record(record: dict[str, Any]) -> bool:
    """Every unresolved record is a retry candidate, whatever failed last time."""
    return not record.get("verified")


def handle_retry(args: argparse.Namespace) -> None:
    config = build_config(args)
    client = OpenAlexClient(config)
    caches = CacheStore(config.cache, enabled=config.use_cache, refresh=config.refresh_cache)
    memo: dict[str, dict[str, Any]] = {}

    refs_paths: list[Path] = []
    if args.refs:
        refs_paths.extend(expand_input_paths(args.refs))
    if args.input:
        for report_path in expand_input_paths(args.input):
            candidate = refs_json_path(report_path)
            if candidate.exists():
                refs_paths.append(candidate)
    if not refs_paths:
        for report_path in expand_input_paths(DEFAULT_INPUT_GLOB):
            candidate = refs_json_path(report_path)
            if candidate.exists():
                refs_paths.append(candidate)

    if not refs_paths:
        print("No reference JSON files found to retry.", file=sys.stderr)
        sys.exit(1)

    total_recovered = 0
    total_retried = 0
    total_to_retry = 0

    for refs_path in refs_paths:
        try:
            payload = json.loads(refs_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        total_to_retry += sum(1 for record in (payload.get("references") or []) if should_retry_record(record))

    print(f"Retrying unresolved references in {len(refs_paths)} sidecar(s) ({total_to_retry} to retry)...")

    for refs_path in refs_paths:
        try:
            payload = json.loads(refs_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"Warning: skipping {refs_path}: {exc}", file=sys.stderr)
            continue

        records = payload.get("references") or []
        prior_summary = payload.get("summary") or {}
        cache = caches.for_report(refs_path)
        stats_before = snapshot_stats(client.stats)
        updated = False
        recovered_here = 0
        retried_here = 0
        retry_targets = [idx for idx, record in enumerate(records) if should_retry_record(record)]
        if retry_targets:
            print(f"\n  {refs_path.name} ({len(retry_targets)} to retry)")

        for attempt_idx, idx in enumerate(retry_targets, start=1):
            record = records[idx]
            if client.stats.halted:
                break

            ref = ParsedReference(
                index=record.get("index", idx + 1),
                title=record.get("original_title") or "",
                url=record.get("original_url") or "",
            )
            retried_here += 1
            refreshed = resolve_reference(
                client,
                cache,
                memo,
                ref,
                config.sim_threshold,
                force_search=config.force_search,
            )
            if refreshed.get("verified") and not record.get("verified"):
                recovered_here += 1
            records[idx] = refreshed
            updated = True
            status = format_record_status(refreshed)
            if refreshed.get("verified") and not record.get("verified"):
                status = f"recovered ({refreshed.get('match_method') or 'verified'})"
            print_ref_progress(attempt_idx, len(retry_targets), ref, refreshed, status=status)

        if updated:
            report_path = Path(payload.get("report") or refs_path.with_suffix(".md"))
            # Counters accumulate onto this sidecar's own history rather than
            # the run-wide totals, which cover every sidecar touched so far.
            carried = carry_stats(prior_summary, stats_delta(client.stats, stats_before))
            payload = summarize_records(report_path, records, carried)
            write_refs_json(payload, refs_path)
            print(
                f"  {refs_path.name}: retried={retried_here} recovered={recovered_here} "
                f"verified={payload['summary']['verified']}/{payload['summary']['total']}"
            )
            total_recovered += recovered_here
            total_retried += retried_here

        if client.stats.halted:
            report_halt_reason(client)
            break

    caches.save_all()
    print(
        f"\nRetry done. recovered={total_recovered} retried={total_retried} "
        f"live_calls={client.stats.live_calls} est_cost=${client.stats.estimated_cost_usd:.4f}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify and enrich research report references using OpenAlex."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--input", default=None, help=f"Glob or file path (default: {DEFAULT_INPUT_GLOB})")
    common.add_argument("--rate", type=float, default=5.0, help="Max OpenAlex requests per second (default: 5)")
    common.add_argument("--sim-threshold", type=float, default=0.8, help="Title similarity threshold (default: 0.8)")
    common.add_argument("--max-cost", type=float, default=None, help="Abort if estimated OpenAlex cost exceeds USD")
    common.add_argument("--retries", type=int, default=4, help="Per-request retry attempts (default: 4)")
    common.add_argument("--backoff-base", type=float, default=1.0, help="Retry backoff base seconds (default: 1.0)")
    common.add_argument("--backoff-cap", type=float, default=30.0, help="Retry backoff cap seconds (default: 30)")
    common.add_argument(
        "--cache", default=CACHE_AUTO,
        help=f"Cache path, or '{CACHE_AUTO}' for one {CACHE_FILE_NAME} per report directory (default: {CACHE_AUTO})",
    )
    common.add_argument("--no-cache", action="store_true", help="Disable persistent cache reads/writes")
    common.add_argument("--refresh-cache", action="store_true", help="Ignore cache and refresh entries")

    parser_verify = subparsers.add_parser("verify", parents=[common], help="Verify references in report markdown files")
    parser_verify.set_defaults(command="verify")

    parser_retry = subparsers.add_parser("retry", parents=[common], help="Retry unresolved references in .json sidecar files")
    parser_retry.add_argument("--refs", default=None, help="Specific .json sidecar file or glob")
    parser_retry.add_argument("--force-search", action="store_true", help="Skip singleton lookup; force title search")
    parser_retry.set_defaults(command="retry")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "verify":
        handle_verify(args)
    elif args.command == "retry":
        handle_retry(args)


if __name__ == "__main__":
    main()
