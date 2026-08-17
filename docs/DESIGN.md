# Design notes

How `handelsregister-cli` talks to the Registerportal (https://www.handelsregister.de),
and why the code is shaped the way it is. Read this before touching `portal.py` or `dk.py`.

## Background

The German commercial register has been free of charge since August 2022 (DiRUG),
but the portal offers **no official API**. It is a Java Server Faces (JSF) /
PrimeFaces application: every interaction is a POST of a server-rendered form,
guarded by a per-view CSRF token (`javax.faces.ViewState`). This tool automates
exactly the clicks a human would perform in a browser, nothing more.

## Request flow

### 1. Search

1. `GET https://www.handelsregister.de` — establishes the session (cookies) and
   renders the start page containing `naviForm`.
2. Submit `naviForm` with an injected hidden field
   `naviForm:erweiterteSucheLink` — this is what PrimeFaces sends when a user
   clicks "Advanced search". The response contains the search `form`.
3. Submit `form` with `form:schlagwoerter` (keywords) and
   `form:schlagwortOptionen` (1 = all keywords, 2 = at least one, 3 = exact
   company name). The response is the result page.

The result page holds a `<table role="grid">`; each result row is a `<tr>` with
a `data-ri` (row index) attribute. Cells: court + register number, name, state,
status, available document links.

### 2. Direct downloads (AD / CD / HD / SI)

Each result row carries PrimeFaces command links whose ids look like

    ergebnissForm:selectedSuchErgebnisFormTable:{row}:j_idt227:{n}:fade_

The visible `<span>` inside the link carries the label (`AD`, `CD`, `HD`, `SI`,
`DK`, `UT`, `VÖ`). Clicking such a link in the browser runs
`PrimeFaces.addSubmitParam('ergebnissForm', {<link-id>: <link-id>, ...}).submit(...)`,
i.e. a plain full-form POST of `ergebnissForm` with the link id as an extra
parameter. Some links (DK/UT/VÖ) additionally send
`property=Global.Dokumentart.XX` and an empty `property2` — we parse those out
of the link's `onclick` attribute rather than hard-coding them.

For AD/CD/HD/SI the response *is* the file (PDF, or XML for SI), served as
`APPLICATION/OCTET-STREAM` with a `Content-Disposition` filename.

After a file download the mechanize browser's "current page" is the file
response, so the search form is gone. Rather than fiddling with history
navigation we simply run a fresh session + search per document. That costs one
extra request per document but is far more robust against server-side view
expiry. The built-in delay keeps the request rate polite either way.

### 3. The DK document folder (Dokumentenansicht)

`DK` navigates to `/rp_web/documents/welcome.xhtml` which renders `dk_form`
with a lazily-loaded PrimeFaces tree (`dk_form:dktree`). This is where the
interesting documents live: shareholder lists (Gesellschafterliste), articles
of association (Gesellschaftsvertrag), founding protocols, applications, etc.

Tree navigation is PrimeFaces partial AJAX. Each expand is a POST with:

    javax.faces.partial.ajax=true
    javax.faces.source=dk_form:dktree
    javax.faces.partial.execute=dk_form:dktree
    javax.faces.partial.render=dk_form:dktree
    javax.faces.behavior.event=expand
    dk_form:dktree_expandNode=<rowkey>
    javax.faces.ViewState=<current view state>

plus headers `Faces-Request: partial/ajax` and `X-Requested-With: XMLHttpRequest`.

The response is a `<partial-response>` XML document. **The rendered tree
nodes sit inside a CDATA section** of the `<update id="dk_form:dktree">`
element — an HTML parser applied to the whole XML will silently drop them, so
we extract the CDATA payload by regex first, then parse it as HTML. Every
partial response also carries a fresh `javax.faces.ViewState` which must be
used for the next request.

Nodes are `<li class="ui-treenode" data-rowkey="...">`; leaves carry
`ui-treenode-leaf` in their class list. We breadth-first expand every non-leaf
rowkey until no new nodes appear.

To download a leaf:

1. AJAX `select` event for the rowkey (same shape as expand, different event),
   which makes the node the server-side selection.
2. Full-form POST of `dk_form` with the Download button's id as a parameter and
   the format radio (`dk_form:radio_dkbuttons`) set to `false` (single file;
   `true` requests a ZIP). The button id (`dk_form:j_idt205` at the time of
   writing) is JSF-generated and **not stable**, so we locate the `<button>`
   containing the text "Download" in the live page instead of hard-coding it.

### Quirks observed in production

- The tree lists the same physical document under several folders ("Weitere
  Urkunden", "Anzeige nach Eintragung", "Anzeige nach Eingang"). We deduplicate
  downloads by SHA-256, not by name.
- Distinct documents can share the same label (two different "Einwilligung
  oder Genehmigung vom 11.03.2026"). Name collisions with different content
  get a ` (2)` suffix.
- Some category leaves ("Musterprotokoll", "Jahresabschluss / Bilanz") can be
  empty; the download POST then returns an HTML page instead of a file. We
  detect files by magic bytes (`%PDF`, `PK`, `<?xml`) and skip HTML responses.
- The court sometimes attaches the identical PDF to two nodes (e.g. a founding
  deed serving as both "Gesellschaftsvertrag" and "Protokoll"); after
  dedup you legitimately get fewer files than tree leaves.

## Rate limiting

The portal historically throttles at roughly 60 requests/hour per client. A
full `fetch --all` on a young GmbH is ~50 requests (search + expands + selects
+ downloads). The client sleeps `--delay` seconds (default 3) between
requests. Do not run this in tight loops over many companies; if you need bulk
data, use a commercial provider instead.

## Module layout

| Module      | Responsibility |
|-------------|----------------|
| `portal.py` | Session setup, search, result parsing, direct downloads |
| `dk.py`     | DK page: tree expansion, node selection, leaf downloads |
| `models.py` | Dataclasses shared across modules |
| `files.py`  | Filename sanitising, checksum dedupe, collision suffixes |
| `cli.py`    | argparse CLI (`hreg search/tree/fetch`) |

`portal.py` and `dk.py` contain all portal-specific fragility; everything else
is plain logic and covered by offline tests in `tests/` (recorded fixtures, no
network).

## Prior art

- [bundesAPI/handelsregister](https://github.com/bundesAPI/handelsregister)
  pioneered the search automation; document download has been an open TODO
  there since 2022. This project is an independent implementation inspired by
  it.
- [handelsregister.ai](https://handelsregister.ai) is a commercial hosted API
  with the same capability plus monitoring; the right choice for bulk or
  SLA-bound use cases.
