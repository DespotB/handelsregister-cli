# handelsregister-cli

[![CI](https://github.com/DespotB/handelsregister-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/DespotB/handelsregister-cli/actions/workflows/ci.yml)

**Search the German commercial register (Handelsregister) and download all registry
documents — including the Gesellschafterliste (shareholder list) and
Gesellschaftsvertrag (articles of association) — from the command line or from Python.**

The official portal [handelsregister.de](https://www.handelsregister.de) has been
free of charge since August 2022, but offers **no API**: every document sits behind
a JavaServer-Faces UI that wants you to click through a search form and a document
tree, per company, per document. This tool automates exactly those clicks.

The well-known [bundesAPI/handelsregister](https://github.com/bundesAPI/handelsregister)
project automates the *search*; document download has been an open TODO there since
2022. `handelsregister-cli` is an independent implementation that does both.

> Suchbegriffe / keywords: Handelsregisterauszug herunterladen, Gesellschafterliste
> download, Gesellschaftsvertrag PDF, Handelsregister API, Registerportal automation,
> German commercial register, company registry Germany.

## What it does, precisely

For any company registered in Germany (GmbH, UG, AG, KG, e.K., …):

1. **Search** the register by keywords or exact company name
   (court, register number, state, status per result).
2. **Download the directly served documents** of a result:
   | Code | Document |
   |------|----------|
   | `AD` | Aktueller Ausdruck — current registry printout (PDF) |
   | `CD` | Chronologischer Ausdruck — chronological printout (PDF) |
   | `HD` | Historischer Ausdruck — historical printout, older companies only (PDF) |
   | `SI` | Strukturierter Registerinhalt — structured register content (XML) |
3. **Walk the DK document folder** ("Dokumentenansicht") — the tree that holds the
   substantive filings — and download every document in it:
   Gesellschafterlisten (shareholder lists), Gesellschaftsverträge / Satzungen
   (articles of association), Gründungsprotokolle, Handelsregisteranmeldungen,
   Listen der Übernehmer, Einwilligungen, and whatever else the court filed.
4. **Deduplicate and name files sensibly.** The portal lists the same physical PDF
   under up to three folders; downloads are deduplicated by SHA-256, name
   collisions between *different* documents get a ` (2)` suffix, and a
   `manifest.json` records every file with its checksum, size and origin.

No accounts, no API keys, no fees — the register is free by law
([DiRUG](https://www.bmj.de/DE/themen/finanzen_und_anlegerschutz/digitalisierung_gesellschaftsrecht/digitalisierung_gesellschaftsrecht_node.html)).

## Install

```bash
uv tool install git+https://github.com/DespotB/handelsregister-cli
# or: pipx install git+https://github.com/DespotB/handelsregister-cli
# or: pip install git+https://github.com/DespotB/handelsregister-cli
```

Python ≥ 3.9. Dependencies: `mechanize`, `beautifulsoup4`.

**AI agents / coding assistants:** see [AGENTS.md](AGENTS.md) for a
self-contained install-and-use recipe (Claude Code users can install the
[plugin](#claude-code-plugin) instead).

## CLI usage

```bash
# 1. Find the company
hreg search "arcneo"
# [0] arcneo GmbH
#     Berlin District court Berlin (Charlottenburg) HRB 261478 | Berlin | currently registered
#     documents: AD, CD, DK, SI, UT, VÖ

# 2. See what's in its document folder (no downloads yet)
hreg tree "arcneo" --register "HRB 261478"

# 3. Download everything into ./arcneo GmbH/
hreg fetch "arcneo" --register "HRB 261478"

# Only the current printout and the shareholder-list folder:
hreg fetch "arcneo" --docs AD,DK -o ./arcneo-docs

# Machine-readable output for scripting:
hreg search "arcneo" --json
hreg fetch "arcneo" --json > result.json
```

Useful flags: `--mode exact|all|any` (keyword matching), `--select N` /
`--register "HRB …"` (pick a result row), `--delay SECONDS` (default 3, see
[Rate limits](#rate-limits-and-fair-use)).

## Library usage

```python
from handelsregister_cli import Portal
from handelsregister_cli.files import FileSink, looks_like_document

portal = Portal("arcneo GmbH", mode="all")
hits = portal.search()
company = hits[0]

# Direct downloads (AD / CD / HD / SI)
pdf = portal.fetch_direct(company.index, "AD")

# The DK document folder
dk = portal.open_dk(company.index)
sink = FileSink("out/")
for node in dk.walk_tree().values():
    if node.leaf and "Gesellschafter" in node.label:
        data = dk.download_leaf(node.rowkey)
        if looks_like_document(data):
            sink.write(node.label, data, source=f"dk:{node.rowkey}")
```

## How it works

The portal is a JSF/PrimeFaces application. The tool replays the exact form
submissions a browser performs: the advanced-search form, the PrimeFaces command
links behind each document code, and the partial-AJAX tree expansion of the
document view (`Faces-Request: partial/ajax`, ViewState tracking, CDATA-wrapped
tree updates). [docs/DESIGN.md](docs/DESIGN.md) documents the wire format and
all known quirks — read it before filing a "layout changed" issue.

**This is screen-scraping.** It is inherently fragile: any portal redesign can
break it. Offline tests run against recorded responses; if the portal changes,
please open an issue with the failing command and Python version.

## Rate limits and fair use

- The portal historically throttles at roughly **60 requests/hour** per client.
  A full `fetch` of a young GmbH is ~50 requests. The default `--delay 3`
  keeps you polite; don't lower it to loop over company lists.
- This tool is built for **targeted, occasional lookups** (due diligence on a
  counterparty, pulling your own company's filings, KYC on a handful of
  entities). It deliberately has no bulk/crawl mode. For bulk or SLA-bound
  needs use a commercial provider (e.g. handelsregister.ai, North Data,
  OpenCorporates).
- You are responsible for complying with the portal's
  [terms of use](https://www.handelsregister.de) and, when re-using the data,
  with GDPR — registry documents contain personal data (names, birth dates,
  addresses of directors and shareholders).

## Limitations

- No captcha solving; if the portal ever gates a request, the tool fails
  loudly instead of working around it.
- `UT` (Unternehmensträgerdaten) and `VÖ` (Veröffentlichungen) are HTML views,
  not files, and are currently not fetched.
- One company per invocation, by design.

## Claude Code plugin

The repo doubles as a Claude Code plugin marketplace. Inside Claude Code:

```
/plugin marketplace add DespotB/handelsregister-cli
/plugin install handelsregister@handelsregister-cli
```

Then ask for e.g. `/handelsregister arcneo GmbH` — the skill installs the CLI on
first use (uv/pipx/pip, whichever is available), runs the fetch and reports the
downloaded files.

## Codex CLI (Agent Skills)

Codex supports the same open [Agent Skills](https://learn.chatgpt.com/docs/build-skills)
format (`SKILL.md`), so the bundled skill works there too — copy it into your
skills directory:

```bash
git clone https://github.com/DespotB/handelsregister-cli /tmp/hrcli
mkdir -p ~/.codex/skills
cp -r /tmp/hrcli/skills/handelsregister ~/.codex/skills/
```

Then ask Codex for registry documents in natural language (skills support is
experimental in Codex; enable it in your Codex config if needed).

## Gemini CLI (extension)

The repo is also a Gemini CLI extension (`gemini-extension.json` + a
`/handelsregister` command):

```bash
gemini extensions install https://github.com/DespotB/handelsregister-cli
```

## Development

```bash
git clone https://github.com/DespotB/handelsregister-cli
cd handelsregister-cli
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest        # offline tests against recorded fixtures
.venv/bin/ruff check src tests
```

## Prior art & credits

- [bundesAPI/handelsregister](https://github.com/bundesAPI/handelsregister) —
  pioneered the search automation; this project started as an attempt to close
  its document-download TODO and became an independent implementation.
- [Lilith Wittmann: "Wir befreien das Handelsregister"](https://lilithwittmann.medium.com/bund-dev-wir-befreien-das-handelsregister-8168ad46b4e) —
  background on why the register is free but still hard to use programmatically.

## License

MIT
