"""The ``hreg`` command line interface.

Subcommands:

* ``hreg search "term"``  — list matching companies
* ``hreg tree "term"``    — show the DK document tree without downloading
* ``hreg fetch "term"``   — download registry documents (default: everything)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .files import FileSink, clean_label, looks_like_document
from .models import CompanyHit
from .portal import DIRECT_LABELS, Portal, PortalError

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
