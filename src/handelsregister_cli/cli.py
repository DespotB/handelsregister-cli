"""The ``hreg`` command line interface.

Subcommands:

* ``hreg search "term"``        — list matching companies
* ``hreg tree "term"``          — show the DK document tree without downloading
* ``hreg fetch "term"``         — download registry documents (default: everything)
* ``hreg announcements``        — date-based Registerbekanntmachungen search
* ``hreg watch``                — cron-friendly diff run: report only new announcements / search hits
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

from . import __version__
from .announcements import CATEGORIES, LAND_CODES, AnnouncementsPortal, matches_keywords
from .files import FileSink, clean_label, looks_like_document
from .models import CompanyHit
from .portal import DIRECT_LABELS, Portal, PortalError
from .watch import WatchState

DIRECT_NAMES = {
    "AD": "Aktueller Ausdruck (AD)",
    "CD": "Chronologischer Ausdruck (CD)",
    "HD": "Historischer Ausdruck (HD)",
    "SI": "Strukturierter Registerinhalt (SI)",
}


def _select_row(hits: list, args) -> CompanyHit:
    if not hits:
        sys.exit("no results")
    if args.register:
        wanted = args.register.replace(" ", "").upper()
        for hit in hits:
            if hit.register_num and hit.register_num.replace(" ", "").upper().startswith(wanted):
                return hit
        sys.exit(f"no result with register number {args.register!r}")
    if args.select >= len(hits):
        sys.exit(f"--select {args.select} out of range (got {len(hits)} results)")
    return hits[args.select]


def cmd_search(args) -> None:
    portal = Portal(args.keywords, mode=args.mode, delay=args.delay)
    hits = portal.search()
    if args.json:
        print(json.dumps([h.as_dict() for h in hits], ensure_ascii=False, indent=2))
        return
    for hit in hits:
        print(f"[{hit.index}] {hit.name}")
        print(f"    {hit.court} | {hit.state} | {hit.status}")
        print(f"    documents: {', '.join(hit.doc_labels) or '-'}")


def cmd_tree(args) -> None:
    portal = Portal(args.keywords, mode=args.mode, delay=args.delay)
    hits = portal.search()
    hit = _select_row(hits, args)
    print(f"# {hit.name} ({hit.register_num})", file=sys.stderr)
    dk = portal.open_dk(hit.index)
    nodes = dk.walk_tree()
    if args.json:
        print(
            json.dumps(
                [{"rowkey": n.rowkey, "label": n.label, "leaf": n.leaf} for n in nodes.values()],
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    for node in nodes.values():
        indent = "  " * (node.rowkey.count("_"))
        marker = "*" if node.leaf else "+"
        print(f"{indent}{marker} {node.label}")


def cmd_fetch(args) -> None:
    portal = Portal(args.keywords, mode=args.mode, delay=args.delay)
    hits = portal.search()
    hit = _select_row(hits, args)
    print(f"fetching documents for: {hit.name} ({hit.register_num})", file=sys.stderr)

    outdir = Path(args.out or clean_label(hit.name))
    sink = FileSink(outdir)
    wanted = [d.strip().upper() for d in args.docs.split(",")] if args.docs else None
    downloads = []
    skipped = []

    def want(label: str) -> bool:
        return wanted is None or label in wanted

    # 1. Directly served documents (AD/CD/HD/SI).
    for label in DIRECT_LABELS:
        if not want(label) or label not in hit.doc_labels:
            continue
        try:
            data = portal.fetch_direct(hit.index, label)
        except PortalError as exc:
            skipped.append((label, str(exc)))
            continue
        if not looks_like_document(data):
            skipped.append((label, "portal returned no file"))
            continue
        dl = sink.write(DIRECT_NAMES.get(label, label), data, source=f"direct:{label}")
        if dl:
            downloads.append(dl)
            print(f"  {dl.path.name} ({dl.size} bytes)", file=sys.stderr)

    # 2. The DK document folder (Gesellschafterliste, Gesellschaftsvertrag, ...).
    if (wanted is None or "DK" in wanted) and "DK" in hit.doc_labels:
        dk = portal.open_dk(hit.index)
        nodes = dk.walk_tree()
        leaves = [n for n in nodes.values() if n.leaf]
        print(f"  DK tree: {len(leaves)} document nodes", file=sys.stderr)
        for node in leaves:
            data = dk.download_leaf(node.rowkey)
            if not looks_like_document(data):
                skipped.append((node.label, "empty category / no file"))
                continue
            dl = sink.write(node.label, data, source=f"dk:{node.rowkey}")
            if dl:
                downloads.append(dl)
                print(f"  {dl.path.name} ({dl.size} bytes)", file=sys.stderr)

    manifest = {
        "company": hit.as_dict(),
        "query": {"keywords": args.keywords, "mode": args.mode},
        "downloads": [d.as_dict() for d in downloads],
        "skipped": [{"label": lb, "reason": rs} for lb, rs in skipped],
    }
    (outdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    else:
        print(f"{len(downloads)} files -> {outdir}/ (deduplicated; see manifest.json)")


def normalize_date(value: str) -> str:
    """Accept ``DD.MM.YYYY`` or ``YYYY-MM-DD``; return the portal's ``DD.MM.YYYY``."""
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(value, fmt).replace(
                tzinfo=_dt.timezone.utc
            ).strftime("%d.%m.%Y")
        except ValueError:
            continue
    raise ValueError(f"not a date: {value!r} (use DD.MM.YYYY or YYYY-MM-DD)")


def _resolve_category(value: str) -> str:
    """Map a category argument (number or name fragment) to the portal value."""
    if value in CATEGORIES:
        return value
    matches = [k for k, v in CATEGORIES.items() if value.lower() in v.lower()]
    if len(matches) != 1:
        opts = ", ".join(f"{k}={v}" for k, v in CATEGORIES.items())
        sys.exit(f"--category {value!r} is ambiguous or unknown; use one of: {opts}")
    return matches[0]


def _announcement_dates(args) -> tuple:
    today = _dt.datetime.now(tz=_dt.timezone.utc).astimezone().date()
    if args.days is not None:
        return (today - _dt.timedelta(days=args.days)).strftime("%d.%m.%Y"), today.strftime("%d.%m.%Y")
    date_to = normalize_date(args.to) if args.to else today.strftime("%d.%m.%Y")
    date_from = normalize_date(getattr(args, "from")) if getattr(args, "from") else date_to
    return date_from, date_to


def _run_announcements_search(args) -> tuple:
    date_from, date_to = _announcement_dates(args)
    if args.land and args.land.upper() not in LAND_CODES:
        sys.exit(f"--land {args.land!r} unknown; use one of: {', '.join(sorted(LAND_CODES))}")
    portal = AnnouncementsPortal(delay=args.delay)
    anns = portal.search(
        date_from,
        date_to,
        land=args.land.upper() if args.land else "",
        court=args.court or "",
        seat=args.sitz or "",
        category=_resolve_category(args.category) if args.category else "",
    )
    anns = [a for a in anns if matches_keywords(a, args.keyword or [])]
    return portal, anns


def cmd_announcements(args) -> None:
    portal, anns = _run_announcements_search(args)
    if args.details:
        for ann in anns:
            portal.fetch_detail(ann)
    if args.json:
        print(json.dumps([a.as_dict() for a in anns], ensure_ascii=False, indent=2))
        return
    for ann in anns:
        print(f"{ann.date}  {ann.category}")
        print(f"    {ann.state} {ann.court} {ann.register_num or ''}".rstrip())
        print(f"    {ann.name} – {ann.seat}")
        if ann.detail and ann.detail.get("text"):
            print(f"    {ann.detail['text'][:300]}")
        print()
    print(f"{len(anns)} announcements", file=sys.stderr)


def _notify(cmd: str, payload: dict) -> None:
    subprocess.run(
        cmd, shell=True, input=json.dumps(payload, ensure_ascii=False), text=True, check=False
    )


def cmd_watch(args) -> None:
    state = WatchState(Path(args.state).expanduser())
    news = []

    portal, anns = _run_announcements_search(args)
    for ann in state.new_announcements(anns):
        if args.details:
            portal.fetch_detail(ann)
        news.append({"type": "announcement", **ann.as_dict()})

    for query in args.search or []:
        hits = Portal(query, mode="all", delay=args.delay).search()
        keyed = [
            (f"{h.court}|{h.register_num or h.name}", h.as_dict())
            for h in hits
        ]
        for _, payload in state.new_search_hits(query, keyed):
            news.append({"type": "search", "query": query, **payload})

    state.save()

    for item in news:
        if args.notify_cmd:
            _notify(args.notify_cmd, item)
    if args.json:
        print(json.dumps(news, ensure_ascii=False, indent=2))
    else:
        for item in news:
            if item["type"] == "announcement":
                print(f"NEW {item['date']} {item['category']}: {item['name']} – {item['seat']} ({item['register_num']})")
            else:
                print(f"NEW result for {item['query']!r}: {item['name']} ({item['register_num']})")
        print(f"{len(news)} new items", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hreg",
        description=(
            "Search the German commercial register (handelsregister.de) and download "
            "registry documents: printouts (AD/CD/HD), structured XML (SI) and the DK "
            "document folder incl. Gesellschafterliste and Gesellschaftsvertrag."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, with_row=False):
        p.add_argument("keywords", help="search keywords, e.g. a company name")
        p.add_argument(
            "--mode",
            choices=["all", "any", "exact"],
            default="all",
            help="keyword matching: all keywords (default), any keyword, exact name",
        )
        p.add_argument(
            "--delay",
            type=float,
            default=3.0,
            help="seconds to sleep between requests (default: 3; be polite)",
        )
        p.add_argument("--json", action="store_true", help="machine-readable output")
        if with_row:
            p.add_argument(
                "--select", type=int, default=0, help="result row to use (default: 0 = first)"
            )
            p.add_argument(
                "--register",
                help='pick the result matching this register number, e.g. "HRB 261478"',
            )

    p_search = sub.add_parser("search", help="search companies")
    common(p_search)
    p_search.set_defaults(func=cmd_search)

    p_tree = sub.add_parser("tree", help="list the DK document tree of one company")
    common(p_tree, with_row=True)
    p_tree.set_defaults(func=cmd_tree)

    p_fetch = sub.add_parser("fetch", help="download registry documents of one company")
    common(p_fetch, with_row=True)
    p_fetch.add_argument(
        "--docs",
        help=(
            "comma-separated subset to download, from: AD,CD,HD,SI,DK "
            "(default: everything available)"
        ),
    )
    p_fetch.add_argument("-o", "--out", help="output directory (default: ./<company name>/)")
    p_fetch.set_defaults(func=cmd_fetch)

    def announcement_args(p):
        p.add_argument("--from", dest="from", metavar="DATE", default=None,
                       help="start date (DD.MM.YYYY or YYYY-MM-DD; default: --to)")
        p.add_argument("--to", default=None, help="end date (default: today)")
        p.add_argument("--days", type=int, default=None,
                       help="shortcut: last N days up to today (overrides --from/--to)")
        p.add_argument("--land", help="Bundesland code, e.g. BE, BY, NW")
        p.add_argument("--court", help='register court, e.g. "Berlin (Charlottenburg)"')
        p.add_argument("--sitz", help="seat of the company")
        p.add_argument("--category", help="1=Löschungsankündigung 2=UmwG 3=neue Dokumente 4=Sonstige 5=Sonderregister (number or name fragment)")
        p.add_argument("--keyword", action="append",
                       help="only announcements containing this keyword (repeatable, OR-matched)")
        p.add_argument("--details", action="store_true",
                       help="also fetch the full announcement text (one extra request each)")
        p.add_argument("--delay", type=float, default=3.0,
                       help="seconds to sleep between requests (default: 3; be polite)")
        p.add_argument("--json", action="store_true", help="machine-readable output")

    p_ann = sub.add_parser(
        "announcements",
        help="search Registerbekanntmachungen by date (Löschungsankündigungen, UmwG, neue Dokumente, …)",
    )
    announcement_args(p_ann)
    p_ann.set_defaults(func=cmd_announcements)

    p_watch = sub.add_parser(
        "watch",
        help="cron-friendly diff run: report only announcements/search results not seen before",
    )
    announcement_args(p_watch)
    p_watch.add_argument("--state", default="~/.hreg-watch.json",
                         help="state file with seen items (default: ~/.hreg-watch.json)")
    p_watch.add_argument("--search", action="append", metavar="QUERY",
                         help="also watch a normal register search for new companies (repeatable)")
    p_watch.add_argument("--notify-cmd", metavar="CMD",
                         help="shell command run once per new item, item JSON on stdin")
    p_watch.set_defaults(func=cmd_watch)
    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except PortalError as exc:
        sys.exit(f"portal error: {exc}")
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
