---
name: ship-it
description: >-
  Run tests, secret-scan changes, commit with an auto-generated message if the
  gate passes, and push to origin. Use when the user wants to finalize work,
  "ship it", or asks to test, commit, and push.
---

# Ship It

Test → secret scan → commit → push for this workspace.

**Runner:** `.cursor/skills/ship-it/scripts/ship_it.py`

| Command | Purpose |
|---|---|
| `check` | Secret-scan changed files, then run pytest (ship gate) |
| `test` | Run pytest only |
| `scan` | Secret-scan changed (or `--staged`) files |

```bash
python .cursor/skills/ship-it/scripts/ship_it.py check
python .cursor/skills/ship-it/scripts/ship_it.py test
python .cursor/skills/ship-it/scripts/ship_it.py scan --staged
```

---

## Workflow

Run sequentially. **Stop on any failure** — do not commit or push.

```
- [ ] 1 ship_it.py check  (or test + scan)
- [ ] 2 Analyze git status / diff; draft commit message
- [ ] 3 Stage safe files only (never .env)
- [ ] 4 Commit via HEREDOC
- [ ] 5 Push origin HEAD
```

### 1. Gate

```bash
python .cursor/skills/ship-it/scripts/ship_it.py check
```

If `check` fails (secrets or tests), report the failure and stop.

### 2. Commit prep

- `git status`, `git diff`, `git diff --staged`, recent `git log`
- Exclude secrets: `.env`, credentials, private keys
- Prefer staging intentional paths over blind `git add .` when untracked noise exists (`project/`, `work`, `output/` are gitignored)

### 3. Commit

```bash
git add <paths>
git commit -m "$(cat <<'EOF'
Concise why-focused message.

EOF
)"
```

### 4. Push

```bash
git push -u origin HEAD
```

If push needs a pull/rebase first, tell the user — do not force-push `main`/`master`.

---

## Hard rules

- Never commit or stage `.env`
- Never `--no-verify` / skip hooks unless the user explicitly asks
- Never amend unless the user's amend rules are fully met
- Never update git config
- Auto-generate a short commit message focused on why
- After push, report the branch and remote URL

## Examples

**User:** "Ship it."

1. `python .cursor/skills/ship-it/scripts/ship_it.py check`
2. On success → stage, commit, `git push -u origin HEAD`
3. Report success

**User:** "Ship it." (tests fail)

1. Gate fails
2. Report failures; do not commit or push
