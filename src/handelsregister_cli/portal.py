"""Session handling, company search and direct document downloads.

The Registerportal is a JSF/PrimeFaces application without an API; see
docs/DESIGN.md for the full request-flow write-up. Everything here mimics the
exact form submissions a browser would perform.
"""
from __future__ import annotations

import re
import time

import mechanize
from bs4 import BeautifulSoup

from .models import CompanyHit

BASE_URL = "https://www.handelsregister.de"

#: form:schlagwortOptionen values understood by the portal.
KEYWORD_MODES = {"all": "1", "any": "2", "exact": "3"}

#: Labels whose result is served directly as a file (response body = document).
DIRECT_LABELS = ("AD", "CD", "HD", "SI")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.5 Safari/605.1.15"
)


class PortalError(RuntimeError):
    """Raised when the portal returns something we cannot interpret."""


def _new_browser() -> mechanize.Browser:
    br = mechanize.Browser()
    br.set_handle_robots(False)
    br.set_handle_refresh(False)
    br.addheaders = [
        ("User-Agent", USER_AGENT),
        ("Accept-Language", "de-DE,de;q=0.9"),
        ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    ]
    return br


def _parse_hit(row, index: int) -> CompanyHit:
    cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
    court = cells[1] if len(cells) > 1 else ""
    # Register number: HRA/HRB/GnR/VR/PR + digits, optional single-letter suffix
    # (e.g. "HRB 261478 B" in Berlin).
    m = re.search(r"(HRA|HRB|GnR|VR|PR)\s*\d+(\s+[A-Z])?(?!\w)", court)
    return CompanyHit(
        index=index,
        name=cells[2] if len(cells) > 2 else "",
        court=court,
        register_num=m.group(0) if m else None,
        state=cells[3] if len(cells) > 3 else "",
        status=cells[4] if len(cells) > 4 else "",
    )


def parse_search_results(html: str) -> list[CompanyHit]:
    """Parse the result page into :class:`CompanyHit` objects."""
    soup = BeautifulSoup(html, "html.parser")
    grid = soup.find("table", role="grid")
    if grid is None:
        return []
    hits = []
    for row in grid.find_all("tr"):
        ri = row.get("data-ri")
        if ri is None:
            continue
        hit = _parse_hit(row, int(ri))
        hit.doc_labels = sorted(parse_doc_links(html, hit.index).keys())
        hits.append(hit)
    return hits


def parse_doc_links(html: str, row: int) -> dict[str, tuple[str, dict[str, str]]]:
    """Extract the document command links of one result row.

    Returns ``{label: (link_id, extra_params)}`` where *extra_params* are the
    additional submit parameters PrimeFaces would send (parsed from the link's
    ``onclick`` handler, e.g. ``property=Global.Dokumentart.DK``).
    """
    soup = BeautifulSoup(html, "html.parser")
    prefix = re.compile(rf"^ergebnissForm:selectedSuchErgebnisFormTable:{row}:")
    links: dict[str, tuple[str, dict[str, str]]] = {}
    for a in soup.find_all("a", id=prefix):
        span = a.find("span")
        if span is None:
            continue
        label = span.get_text(strip=True)
        extra: dict[str, str] = {}
        m = re.search(r"'property':'([^']*)'", a.get("onclick", ""))
        if m:
            extra["property"] = m.group(1)
            extra["property2"] = ""
        links[label] = (a["id"], extra)
    return links


class Portal:
    """One search context against the Registerportal.

    A :class:`Portal` is bound to a keyword query. Each network-touching call
    runs a *fresh* session + search internally: after a file download the JSF
    view is consumed, and re-searching is far more robust than trying to
    resurrect server-side state (see docs/DESIGN.md). ``delay`` seconds of
    sleep are inserted before each new session to stay well under the
    portal's rate limit.
    """

    def __init__(self, keywords: str, mode: str = "all", delay: float = 3.0, timeout: int = 30):
        if mode not in KEYWORD_MODES:
            raise ValueError(f"mode must be one of {sorted(KEYWORD_MODES)}")
        self.keywords = keywords
        self.mode = mode
        self.delay = delay
        self.timeout = timeout
        self._first_request_done = False

    # -- internals ---------------------------------------------------------

    def _sleep(self):
        if self._first_request_done and self.delay:
            time.sleep(self.delay)
        self._first_request_done = True

    def _search_session(self) -> tuple[mechanize.Browser, str]:
        """Fresh browser, logged-out search; returns (browser, result_html)."""
        self._sleep()
        br = _new_browser()
        br.open(BASE_URL, timeout=self.timeout)
        # "Advanced search" click: PrimeFaces submits naviForm with this
        # hidden parameter; mechanize doesn't run JS, so we inject it.
        br.select_form(name="naviForm")
        br.form.new_control(
            "hidden", "naviForm:erweiterteSucheLink", {"value": "naviForm:erweiterteSucheLink"}
        )
        br.submit()
        br.select_form(name="form")
        br["form:schlagwoerter"] = self.keywords
        br["form:schlagwortOptionen"] = [KEYWORD_MODES[self.mode]]
        resp = br.submit()
        return br, resp.read().decode("utf-8")

    # -- public API --------------------------------------------------------

    def search(self) -> list[CompanyHit]:
        """Run the search and return all result rows."""
        _, html = self._search_session()
        return parse_search_results(html)

    def fetch_direct(self, row: int, label: str) -> bytes:
        """Download one directly-served document (AD, CD, HD or SI) for *row*.

        Raises :class:`PortalError` if the label is not offered for that row.
        """
        br, html = self._search_session()
        links = parse_doc_links(html, row)
        if label not in links:
            raise PortalError(
                f"document type {label!r} not available for row {row} "
                f"(available: {sorted(links)})"
            )
        link_id, extra = links[label]
        br.select_form(name="ergebnissForm")
        br.form.new_control("hidden", link_id, {"value": link_id})
        for key, value in extra.items():
            br.form.new_control("hidden", key, {"value": value})
        resp = br.submit()
        return resp.read()

    def open_dk(self, row: int):
        """Navigate into the DK document folder of *row*.

        Returns a :class:`handelsregister_cli.dk.DkSession`. Imported lazily to
        keep module dependencies one-directional.
        """
        from .dk import DkSession

        br, html = self._search_session()
        links = parse_doc_links(html, row)
        if "DK" not in links:
            raise PortalError(f"no DK folder for row {row} (available: {sorted(links)})")
        link_id, extra = links["DK"]
        br.select_form(name="ergebnissForm")
        br.form.new_control("hidden", link_id, {"value": link_id})
        for key, value in extra.items():
            br.form.new_control("hidden", key, {"value": value})
        resp = br.submit()
        return DkSession(br, resp.read().decode("utf-8"), delay=self.delay)
