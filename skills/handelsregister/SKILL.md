---
name: handelsregister
description: Search the German commercial register (Handelsregister), download registry documents for a company — Gesellschafterliste (shareholder list), Gesellschaftsvertrag (articles of association), current/chronological printouts (AD/CD), structured XML (SI) — and query date-based Registerbekanntmachungen (Löschungsankündigungen, UmwG announcements, new filings). Use when the user asks for a Handelsregisterauszug, Gesellschafterliste, registry documents, company data from handelsregister.de, or recent register announcements. Invoked as /handelsregister <company name>.
---

# Handelsregister document fetch

Fetch official registry documents for a German company from handelsregister.de
using the `hreg` CLI (from the same repository as this plugin).

## Steps

1. **Ensure the CLI is available.** Run `hreg --version`. If missing, install it
   with the first of these tools that exists on the machine:
   - `uv tool install git+https://github.com/DespotB/handelsregister-cli`
   - `pipx install git+https://github.com/DespotB/handelsregister-cli`
   - `pip install --user git+https://github.com/DespotB/handelsregister-cli`

   If `hreg` is still not found afterwards, the install bin directory is likely
   not on PATH — try `~/.local/bin/hreg --version` and call it by that path.
   If all installers fail, tell the user what to install and stop.

2. **Search first, never guess.** Run:
   `hreg search "<company keywords>" --json`
   - No results: tell the user, suggest broader keywords or `--mode any`.
   - Several plausible results: show name + court + register number and ask
     which one is meant, unless the user already gave a register number.

3. **Fetch.** Default is everything; honour a user's narrower request via `--docs`:
   `hreg fetch "<keywords>" --register "<HRB/HRA number>" -o "<outdir>" --json`
   - Output directory: whatever the user or the project's conventions dictate;
     otherwise `./<company name>/` in the working directory.
   - The command is slow by design (about 3 seconds between requests, a full
     fetch can take a few minutes). Do not lower `--delay` below 3 and do not
     loop over many companies — the portal rate-limits at roughly 60
     requests/hour.

4. **Report.** Read `manifest.json` from the output directory and summarise:
   which documents were downloaded (highlight Gesellschafterlisten and
   Gesellschaftsverträge with their dates), what was skipped and why, and where
   the files are. Mention that duplicates were removed by checksum.

## Announcements and watching

- For "what was announced recently" questions use
  `hreg announcements --days N [--land BE] [--category …] [--keyword …] --json`.
  Categories: Löschungsankündigung, UmwG announcements, new document filings,
  and two "other" buckets. `--details` adds the full text (one extra request
  per item — keep the result set small first).
- **There is no feed of newly registered companies** — since the DiRUG reform
  (Aug 2022) Neueintragungen are not announced anywhere. Say so instead of
  improvising. The closest free approximation is
  `hreg watch --search "<name keyword>"` on a schedule, which reports register
  numbers not seen on a previous run (first run only seeds its state file).

## Notes

- Registry documents contain personal data (names, birth dates, addresses).
  Do not paste their contents into external services without the user asking.
- If the fetch fails with a parsing error, the portal layout may have changed;
  point the user to https://github.com/DespotB/handelsregister-cli/issues
  instead of retrying in a loop.
