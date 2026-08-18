# Handelsregister document fetch (Gemini CLI extension)

This extension wraps the `hreg` CLI from this repository to fetch official
registry documents for German companies from handelsregister.de.

## Rules

1. Ensure the CLI is available: run `hreg --version`. If missing, install with
   the first available tool — `uv tool install`, `pipx install`, or
   `pip install --user` — each with
   `git+https://github.com/DespotB/handelsregister-cli`. If `hreg` is still
   not found, the install bin dir is likely not on PATH: try
   `~/.local/bin/hreg`. If all fail, tell the user and stop.
2. Always search before fetching: `hreg search "<keywords>" --json`.
   If several plausible companies match, ask which one is meant unless the
   user already provided a register number.
3. Fetch with `hreg fetch "<keywords>" --register "<HRB/HRA number>" -o "<outdir>" --json`.
   Honour a narrower request via `--docs AD,CD,SI,DK`. Never lower `--delay`
   below 3 and never loop over company lists: the portal rate-limits at
   roughly 60 requests/hour. A full fetch takes a few minutes by design.
4. Afterwards read `manifest.json` in the output directory and summarise what
   was downloaded (highlight Gesellschafterlisten and Gesellschaftsverträge
   with dates), what was skipped, and where the files are.
5. Registry documents contain personal data (names, birth dates, addresses).
   Do not send their contents to external services unprompted.
6. On parsing errors the portal layout may have changed: point the user to
   https://github.com/DespotB/handelsregister-cli/issues instead of retrying.
