---
name: research-verify
description: >-
  Audit scholarly citations in research reports through OpenAlex. Parses
  numbered Markdown Sources or References blocks, deduplicates lookups, writes
  audit-only JSON sidecars, and supports retry. Use after any report-producing
  research workflow when the user wants bibliographic verification.
---

# Research Citation Audit

**Stage: completed reports → OpenAlex sidecars.**

This skill never rewrites reports. It verifies scholarly works; ordinary
company pages, news, blogs, and other non-scholarly sources are outside
OpenAlex coverage and must not be described as false merely because OpenAlex
cannot resolve them.

**Runner:** `.cursor/skills/research-verify/scripts/verify_references.py`

## Contract

- Input: report Markdown containing a numbered `## Sources` or
  `## References` block.
- Output: `{report}.json` beside each report.
- Files without a source block are skipped.
- DOI, PMID, and arXiv identifiers are resolved directly; remaining scholarly
  titles use OpenAlex search.
- Cache defaults to one `openalex_cache.json` per report directory.
- Verification is an audit, not a report-editing step.

Details and sidecar schema: [reference.md](reference.md).

## Workflow

Scope input to the workflow directory:

```bash
python .cursor/skills/research-verify/scripts/verify_references.py verify \
  --input "work/deep/*.md" --max-cost 1.0
```

Relay per-reference progress. On unresolved or errored records:

```bash
python .cursor/skills/research-verify/scripts/verify_references.py retry \
  --input "work/deep/*.md"
```

Use `--force-search` only when a singleton identifier/title lookup was wrong
or incomplete and title search is the intended fallback.

Interpret results carefully:

- `verified` means OpenAlex found a compatible scholarly record;
- `not_found` means OpenAlex did not resolve it, not that the citation is
  necessarily false;
- `error` means lookup failed and is retryable;
- non-scholarly sources require source-appropriate review outside this skill.

Never print or expose OpenAlex credentials. Follow
`.cursor/rules/valyu-api.mdc` for shared secret and artifact policy.
