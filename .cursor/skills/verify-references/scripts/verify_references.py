#!/usr/bin/env python3
"""Verify and enrich research report references via the OpenAlex API."""

from __future__ import annotations

import argparse
import configparser
import difflib
import glob
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

import requests
from dotenv import load_dotenv

OPENALEX_BASE = "https://api.openalex.org"
DEFAULT_CACHE_PATH = "output/openalex_cache.json"
DEFAULT_INPUT_GLOB = "output/*.md"
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
PMID_RE = re.compile(r"(?:pubmed\.ncbi\.nlm\.nih\.gov/(?:\d+|PMC\d+)|/(\d{7,8})(?:/|$|\?))", re.IGNORECASE)
PMCID_RE = re.compile(r"(?:/|pmc/)(PMC\d+)", re.IGNORECASE)
ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)
BIORXIV_RE = re.compile(r"(?:biorxiv|medrxiv|chemrxiv)\.org/content/10\.1101/[^\s?#]+", re.IGNORECASE)
COST_SINGLETON = 0.0
COST_LIST = 0.0001


class RateLimitExhausted(Exception):
    """Daily OpenAlex budget exhausted after retries."""


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
    rate_limited: bool = False


@dataclass
class VerifyConfig:
    api_key: str
    rate: float = 5.0
    sim_threshold: float = 0.8
    max_cost: Optional[float] = None
    retries: int = 4
    backoff_base: float = 1.0
    backoff_cap: float = 30.0
    use_cache: bool = True
    refresh_cache: bool = False
    force_search: bool = False
    cache_path: Path = field(default_factory=lambda: Path(DEFAULT_CACHE_PATH))


def find_env_file() -> Path:
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        env_file = parent / ".env"
        if env_file.exists():
            return env_file
    return Path.cwd() / ".env"


def read_ini_section(env_path: Path, section_name: str) -> dict[str, str]:
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


def get_openalex_api_key() -> str:
    env_path = find_env_file()
    load_dotenv(env_path)
    section = read_ini_section(env_path, "openalex")
    api_key = os.getenv("OPENALEX_API_KEY") or section.get("api_key", "").strip()
    if not api_key:
        print(
            "Error: OPENALEX_API_KEY not found in environment or [openalex] section of .env.",
            file=sys.stderr,
        )
        sys.exit(1)
    return api_key


def normalize_title(title: str) -> str:
    cleaned = re.sub(r"\s+", " ", title.lower().strip())
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    return cleaned


def normalize_doi(raw: str) -> str:
    doi = raw.strip().lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = doi.rstrip(".,;)")
    return doi


def dedup_key(identifier: Optional[Identifier], title: str) -> str:
    if identifier:
        if identifier.type == "doi":
            return f"doi:{normalize_doi(identifier.value)}"
        return f"{identifier.type}:{identifier.value.lower()}"
    return f"title:{normalize_title(title)}"


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
    if pmid_match and pmid_match.group(1):
        return Identifier("pmid", pmid_match.group(1))

    if "/pubmed.ncbi.nlm.nih.gov/" in url_lower:
        tail = url.rstrip("/").split("/")[-1]
        if tail.isdigit():
            return Identifier("pmid", tail)
        if tail.upper().startswith("PMC"):
            return Identifier("pmcid", tail.upper())

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
    matches = sorted(Path(p) for p in glob.glob(pattern))
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
            raise RateLimitExhausted(
                f"Estimated OpenAlex cost ${projected:.4f} exceeds --max-cost ${self.config.max_cost:.4f}"
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
                    raise RateLimitExhausted(f"network_error: {last_error}") from exc
                self._sleep_backoff(attempt, None)
                continue

            if response.status_code == 404:
                return None

            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                if attempt >= self.config.retries:
                    raise RateLimitExhausted(f"rate_limited: {last_error}")
                retry_after = response.headers.get("Retry-After")
                self._sleep_backoff(attempt, retry_after)
                continue

            if not response.ok:
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                if attempt >= self.config.retries:
                    raise RateLimitExhausted(f"network_error: {last_error}")
                self._sleep_backoff(attempt, None)
                continue

            self.stats.live_calls += 1
            self.stats.estimated_cost_usd += cost
            return response.json()

        raise RateLimitExhausted(last_error or "unknown_error")

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
        return {"api_key": self.config.api_key, "select": SELECT_FIELDS}

    def lookup_singleton(self, identifier: Identifier) -> tuple[Optional[dict[str, Any]], str]:
        if identifier.type == "doi":
            path = f"/works/doi:{identifier.value}"
        elif identifier.type == "pmid":
            path = f"/works/pmid:{identifier.value}"
        elif identifier.type == "pmcid":
            path = f"/works/pmcid:{identifier.value}"
        elif identifier.type == "arxiv":
            path = f"/works/https://arxiv.org/abs/{identifier.value}"
        else:
            return None, "unsupported_identifier"

        url = f"{OPENALEX_BASE}{path}"
        result = self._request_with_retry(url, self._base_params(), COST_SINGLETON)
        if result is None:
            return None, "not_found"
        return result, "singleton"

    def search_by_title(self, title: str) -> tuple[Optional[dict[str, Any]], float, str]:
        params = self._base_params()
        params["filter"] = f"title.search:{title}"
        params["per-page"] = "5"
        url = f"{OPENALEX_BASE}/works"
        payload = self._request_with_retry(url, params, COST_LIST)
        if not payload:
            return None, 0.0, "not_found"
        results = payload.get("results") or []
        if not results:
            return None, 0.0, "not_found"

        normalized = normalize_title(title)
        best = max(
            results,
            key=lambda item: difflib.SequenceMatcher(
                None, normalized, normalize_title(item.get("display_name") or item.get("title") or "")
            ).ratio(),
        )
        similarity = difflib.SequenceMatcher(
            None,
            normalized,
            normalize_title(best.get("display_name") or best.get("title") or ""),
        ).ratio()
        return best, similarity, "title_search"


class ReferenceCache:
    def __init__(self, path: Path, enabled: bool = True, refresh: bool = False):
        self.path = path
        self.enabled = enabled
        self.refresh = refresh
        self.data: dict[str, Any] = {}
        self.dirty = False
        if enabled and not refresh and path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self.data = {}

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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")


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

    if key in memo:
        client.stats.memo_hits += 1
        cached_record = memo[key].copy()
        cached_record.update(
            {
                "index": ref.index,
                "original_title": ref.title,
                "original_url": ref.url,
                "identifier": {"type": identifier.type, "value": identifier.value} if identifier else None,
                "dedup_key": key,
                "cache_hit": True,
            }
        )
        return cached_record

    cached = cache.get(key)
    if cached:
        client.stats.cache_hits += 1
        record = cached.copy()
        record.update(
            {
                "index": ref.index,
                "original_title": ref.title,
                "original_url": ref.url,
                "identifier": {"type": identifier.type, "value": identifier.value} if identifier else None,
                "dedup_key": key,
                "cache_hit": True,
            }
        )
        memo[key] = record
        return record

    record: dict[str, Any] = {
        "index": ref.index,
        "original_title": ref.title,
        "original_url": ref.url,
        "identifier": {"type": identifier.type, "value": identifier.value} if identifier else None,
        "dedup_key": key,
        "verified": False,
        "error": None,
        "attempts": 1,
        "match_method": None,
        "title_similarity": None,
        "openalex": None,
        "cache_hit": False,
    }

    try:
        work: Optional[dict[str, Any]] = None
        match_method = None
        similarity: Optional[float] = None

        if identifier and not force_search:
            work, match_method = client.lookup_singleton(identifier)

        if work is None:
            candidate, similarity, match_method = client.search_by_title(ref.title)
            record["title_similarity"] = round(similarity, 4)
            if candidate and similarity >= sim_threshold:
                work = candidate
            elif candidate:
                record["error"] = "ambiguous"
                record["match_method"] = match_method
                memo[key] = record
                return record
            else:
                record["error"] = "not_found"
                record["match_method"] = match_method
                memo[key] = record
                cache.set(key, {k: v for k, v in record.items() if k not in {"index", "original_title", "original_url"}})
                return record

        if work:
            record["openalex"] = build_openalex_payload(work)
            record["verified"] = True
            record["match_method"] = match_method
            if similarity is not None:
                record["title_similarity"] = round(similarity, 4)
            elif identifier:
                canonical = work.get("display_name") or work.get("title") or ""
                record["title_similarity"] = round(
                    difflib.SequenceMatcher(None, normalize_title(ref.title), normalize_title(canonical)).ratio(),
                    4,
                )

    except RateLimitExhausted as exc:
        message = str(exc)
        if message.startswith("rate_limited"):
            client.stats.rate_limited = True
            record["error"] = "rate_limited"
        elif message.startswith("network_error"):
            record["error"] = "network_error"
            # Fall back to title search once if singleton lookup failed transiently.
            if identifier and not force_search and work is None:
                try:
                    candidate, similarity, match_method = client.search_by_title(ref.title)
                    record["title_similarity"] = round(similarity, 4)
                    if candidate and similarity >= sim_threshold:
                        record["openalex"] = build_openalex_payload(candidate)
                        record["verified"] = True
                        record["match_method"] = match_method
                        record["error"] = None
                except RateLimitExhausted as fallback_exc:
                    if str(fallback_exc).startswith("rate_limited"):
                        client.stats.rate_limited = True
                        record["error"] = "rate_limited"
                    else:
                        record["error"] = "network_error"
        else:
            client.stats.rate_limited = True
            record["error"] = "rate_limited"
        record["attempts"] = client.config.retries + 1

    memo[key] = record
    cache.set(
        key,
        {k: v for k, v in record.items() if k not in {"index", "original_title", "original_url"}},
    )
    return record


def truncate_title(title: str, max_len: int = 55) -> str:
    cleaned = re.sub(r"\s+", " ", title.strip())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1] + "…"


def format_record_status(record: dict[str, Any]) -> str:
    if record.get("cache_hit"):
        return "cache hit"
    if record.get("verified"):
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
    errored = sum(1 for r in records if r.get("error") in {"rate_limited", "network_error"})
    ambiguous = sum(1 for r in records if r.get("error") == "ambiguous")
    not_found = sum(1 for r in records if r.get("error") == "not_found")

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
    show_progress: bool = True,
) -> dict[str, Any]:
    text = report_path.read_text(encoding="utf-8")
    refs = parse_sources_block(text)
    records: list[dict[str, Any]] = []
    stats_before = RequestStats(
        live_calls=client.stats.live_calls,
        cache_hits=client.stats.cache_hits,
        memo_hits=client.stats.memo_hits,
        estimated_cost_usd=client.stats.estimated_cost_usd,
        rate_limited=client.stats.rate_limited,
    )

    for idx, ref in enumerate(refs, start=1):
        if client.stats.rate_limited:
            identifier = extract_identifier(ref.title, ref.url)
            key = dedup_key(identifier, ref.title)
            record = {
                "index": ref.index,
                "original_title": ref.title,
                "original_url": ref.url,
                "identifier": {"type": identifier.type, "value": identifier.value} if identifier else None,
                "dedup_key": key,
                "verified": False,
                "error": "rate_limited",
                "attempts": client.config.retries + 1,
                "match_method": None,
                "title_similarity": None,
                "openalex": None,
                "cache_hit": False,
            }
            records.append(record)
            if show_progress:
                print_ref_progress(idx, len(refs), ref, record)
            continue

        record = resolve_reference(client, cache, memo, ref, sim_threshold, force_search=force_search)
        records.append(record)
        if show_progress:
            print_ref_progress(idx, len(refs), ref, record)

    report_stats = RequestStats(
        live_calls=client.stats.live_calls - stats_before.live_calls,
        cache_hits=client.stats.cache_hits - stats_before.cache_hits,
        memo_hits=client.stats.memo_hits - stats_before.memo_hits,
        estimated_cost_usd=client.stats.estimated_cost_usd - stats_before.estimated_cost_usd,
        rate_limited=client.stats.rate_limited,
    )
    return summarize_records(report_path, records, report_stats)


def write_refs_json(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def handle_verify(args: argparse.Namespace) -> None:
    config = VerifyConfig(
        api_key=get_openalex_api_key(),
        rate=args.rate,
        sim_threshold=args.sim_threshold,
        max_cost=args.max_cost,
        retries=args.retries,
        backoff_base=args.backoff_base,
        backoff_cap=args.backoff_cap,
        use_cache=not args.no_cache,
        refresh_cache=args.refresh_cache,
        cache_path=Path(args.cache),
    )
    client = OpenAlexClient(config)
    cache = ReferenceCache(config.cache_path, enabled=config.use_cache, refresh=config.refresh_cache)
    memo: dict[str, dict[str, Any]] = {}

    input_pattern = args.input or DEFAULT_INPUT_GLOB
    report_paths = expand_input_paths(input_pattern)
    if not report_paths:
        print("No report files to verify.", file=sys.stderr)
        sys.exit(1)

    total_refs = 0
    for report_path in report_paths:
        refs = parse_sources_block(report_path.read_text(encoding="utf-8"))
        total_refs += len(refs)

    print(
        f"Verifying references in {len(report_paths)} report(s) "
        f"({total_refs} reference(s) total)..."
    )
    total_verified = 0

    for report_idx, report_path in enumerate(report_paths, start=1):
        refs = parse_sources_block(report_path.read_text(encoding="utf-8"))
        print(
            f"\n  Report {report_idx}/{len(report_paths)}: {report_path} "
            f"({len(refs)} reference(s))"
        )
        payload = verify_report(report_path, client, cache, memo, config.sim_threshold)
        output_path = refs_json_path(report_path)
        write_refs_json(payload, output_path)
        summary = payload["summary"]
        total_verified += summary["verified"]
        print(
            f"    refs={summary['total']} verified={summary['verified']} "
            f"ambiguous={summary['ambiguous']} not_found={summary['not_found']} "
            f"errored={summary['errored']} -> {output_path.name}"
        )
        if client.stats.rate_limited:
            print("    Stopped early due to rate limit / max cost.", file=sys.stderr)
            break

    cache.save()
    print(
        f"\nDone. {total_verified}/{total_refs} references verified across {len(report_paths)} report(s). "
        f"live_calls={client.stats.live_calls} cache_hits={client.stats.cache_hits} "
        f"memo_hits={client.stats.memo_hits} est_cost=${client.stats.estimated_cost_usd:.4f}"
    )


def should_retry_record(record: dict[str, Any]) -> bool:
    if record.get("verified"):
        return False
    return record.get("error") in {None, "rate_limited", "network_error", "ambiguous", "not_found"}


def handle_retry(args: argparse.Namespace) -> None:
    config = VerifyConfig(
        api_key=get_openalex_api_key(),
        rate=args.rate,
        sim_threshold=args.sim_threshold,
        max_cost=args.max_cost,
        retries=args.retries,
        backoff_base=args.backoff_base,
        backoff_cap=args.backoff_cap,
        use_cache=not args.no_cache,
        refresh_cache=args.refresh_cache,
        force_search=args.force_search,
        cache_path=Path(args.cache),
    )
    client = OpenAlexClient(config)
    cache = ReferenceCache(config.cache_path, enabled=config.use_cache, refresh=config.refresh_cache)
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
        updated = False
        recovered_here = 0
        retried_here = 0
        retry_targets = [idx for idx, record in enumerate(records) if should_retry_record(record)]
        if retry_targets:
            print(f"\n  {refs_path.name} ({len(retry_targets)} to retry)")

        for attempt_idx, idx in enumerate(retry_targets, start=1):
            record = records[idx]
            if client.stats.rate_limited:
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
            report_path = Path(payload.get("report") or refs_path.with_suffix("").with_suffix(".md"))
            payload = summarize_records(report_path, records, client.stats)
            write_refs_json(payload, refs_path)
            print(
                f"  {refs_path.name}: retried={retried_here} recovered={recovered_here} "
                f"verified={payload['summary']['verified']}/{payload['summary']['total']}"
            )
            total_recovered += recovered_here
            total_retried += retried_here

    cache.save()
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
    common.add_argument("--cache", default=DEFAULT_CACHE_PATH, help=f"Persistent cache path (default: {DEFAULT_CACHE_PATH})")
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
