# Instructions for AI agents

You have been pointed at `handelsregister-cli` to fetch official German
commercial-register documents (Handelsregister) — e.g. a Gesellschafterliste
(shareholder list), Gesellschaftsvertrag (articles of association), or a
current printout — for a company. Follow this recipe exactly.

## 1. Install the `hreg` CLI (once)

Check first: `hreg --version`. If missing, install with the **first** of these
tools that exists on the machine:

```bash
uv tool install git+https://github.com/DespotB/handelsregister-cli
# or
pipx install git+https://github.com/DespotB/handelsregister-cli
# or
pip install --user git+https://github.com/DespotB/handelsregister-cli
```

If `hreg` is still not found afterwards, the install bin directory is probably
not on PATH — try `~/.local/bin/hreg --version` and call it by that path.
If all installers fail, report what needs to be installed and stop.

No accounts, API keys, or fees are needed; the register is free by law.

## 2. Search first, never guess

```bash
hreg search "<company keywords>" --json
```

- No results: broaden the keywords or add `--mode any`.
- Several plausible results: show name + court + register number and ask the
  user which one is meant, unless they already gave a register number.

## 3. Fetch

```bash
hreg fetch "<keywords>" --register "<HRB/HRA number>" -o "<outdir>" --json
```

- Default downloads everything; narrow with `--docs AD,CD,SI,DK`
  (Gesellschafterlisten and Gesellschaftsverträge live in the `DK` folder).
- The command is slow **by design** (~3 s between requests; a full fetch takes
  minutes). Never lower `--delay` below 3 and never loop over many companies —
  the portal rate-limits at roughly 60 requests/hour.

## 4. Report

Read `manifest.json` in the output directory and summarise: which documents
were downloaded (highlight Gesellschafterlisten and Gesellschaftsverträge with
their dates), what was skipped and why, and where the files are. Duplicates
are already removed by SHA-256 checksum; "skipped: empty category" entries are
portal-tree duplicates, not errors.

## Rules

- Registry documents contain personal data (names, birth dates, addresses).
  Do not send their contents to external services unless the user asks.
- On parsing errors the portal layout may have changed: point the user to
  https://github.com/DespotB/handelsregister-cli/issues instead of retrying
  in a loop.

## Claude Code

Prefer installing the bundled plugin instead of following this file manually:

```
/plugin marketplace add DespotB/handelsregister-cli
/plugin install handelsregister@handelsregister-cli
```

This provides the `/handelsregister <company>` skill with the same workflow.
