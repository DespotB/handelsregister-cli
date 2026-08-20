"""Registerbekanntmachungen: date-based announcement search and detail retrieval.

Since the DiRUG reform (Aug 2022) new registrations are no longer published as
announcements anywhere — the portal's "Registerbekanntmachungen" section only
carries five categories (Löschungsankündigungen, UmwG notices, new document
filings, …). This module automates that search form; it is the only date-based
feed handelsregister.de offers.
"""
from __future__ import annotations

import re
import time
import urllib.parse

import mechanize
from bs4 import BeautifulSoup

from .models import Announcement
from .portal import BASE_URL, PortalError, _new_browser

#: bekanntMachungenForm:kategorie_input values.
CATEGORIES = {
    "1": "Löschungsankündigung",
    "2": "Registerbekanntmachung nach dem Umwandlungsgesetz",
    "3": "Einreichung neuer Dokumente",
    "4": "Sonstige Registerbekanntmachung",
    "5": "Sonderregisterbekanntmachung OHNE Bezug zum elektr. Register",
}

#: bekanntMachungenForm:land_input values.
LAND_CODES = {
    "BW": "Baden-Württemberg", "BY": "Bayern", "BE": "Berlin", "BR": "Brandenburg",
    "HB": "Bremen", "HH": "Hamburg", "HE": "Hessen", "MV": "Mecklenburg-Vorpommern",
    "NI": "Niedersachsen", "NW": "Nordrhein-Westfalen", "RP": "Rheinland-Pfalz",
    "SL": "Saarland", "SN": "Sachsen", "ST": "Sachsen-Anhalt",
    "SH": "Schleswig-Holstein", "TH": "Thüringen",
}

_REGISTER_RE = re.compile(r"(HRA|HRB|GnR|VR|PR|GsR)\s*\d+(\s+[A-Z])?(?!\w)")
_FIRE_RE = re.compile(r"fireBekanntmachung\d+\('([^']+)',\s*'(\d+)'\)")


def parse_announcements(html: str) -> list[Announcement]:
    """Parse the announcements result page (grouped by date) into a flat list."""
    soup = BeautifulSoup(html, "html.parser")
    dl = soup.find(id=re.compile(r"datalistId_list$"))
    if dl is None:
        return []
    anns: list[Announcement] = []
    date = ""
    for block in dl.find_all(["dt", "dd"], recursive=False):
        if block.name == "dt":
            date = block.get_text(strip=True)
            continue
        for a in block.find_all("a", recursive=False):
            m = _FIRE_RE.search(a.get("onclick", ""))
            label = a.find("label")
            if not m or label is None:
                continue
            lines = [ln.strip() for ln in label.get_text("\n", strip=True).split("\n") if ln.strip()]
            if len(lines) < 3:
                continue
            category, court_line, name_line = lines[0], lines[1], lines[2]
            state = court_line.split()[0] if court_line else ""
            reg = _REGISTER_RE.search(court_line)
            court = court_line[len(state):reg.start()].strip() if reg else court_line[len(state):].strip()
            name, _, seat = name_line.rpartition("–")
            if not name:  # no dash at all: treat whole line as name
                name, seat = seat, ""
            anns.append(
                Announcement(
                    id=m.group(2),
                    date=date,
                    js_date=m.group(1),
                    category=category,
                    state=state,
                    court=court,
                    register_num=reg.group(0) if reg else None,
                    name=name.strip(),
                    seat=seat.strip(),
                )
            )
    return anns


def parse_remote_source(html: str) -> str:
    """Extract the JSF component id behind the ``remoteBekanntmachung`` command."""
    m = re.search(r'remoteBekanntmachung = function\(\) \{PrimeFaces\.ab\(\{s:"([^"]+)"', html)
    if not m:
        raise PortalError("remoteBekanntmachung command not found on announcements page")
    return m.group(1)


def parse_announcement_detail(html: str) -> dict:
    """Parse the einzelBekanntmachung page into a plain dict."""
    soup = BeautifulSoup(html, "html.parser")
    panel = soup.find(id="rrbPanel_content")
    if panel is None:
        raise PortalError("announcement detail panel not found")
    labels = [t for t in (lb.get_text(" ", strip=True) for lb in panel.find_all("label")) if t]
    # Layout: date, court line, category, [entry date + "(Eintragungsdatum)"],
    # name, legal form, seat, text…  The Eintragungsdatum block is absent e.g.
    # on Löschungsankündigungen, so consume it conditionally.
    entry_date = ""
    if "(Eintragungsdatum)" in labels:
        i = labels.index("(Eintragungsdatum)")
        entry_date = labels[i - 1] if i else ""
        labels = labels[: i - 1] + labels[i + 1 :]
    detail = {
        "date": labels[0].replace("(Bekanntmachungsdatum)", "").strip() if labels else "",
        "court_line": labels[1] if len(labels) > 1 else "",
        "category": labels[2] if len(labels) > 2 else "",
        "entry_date": entry_date,
        "name": labels[3] if len(labels) > 3 else "",
        "legal_form": labels[4] if len(labels) > 4 else "",
        "seat": labels[5] if len(labels) > 5 else "",
        "text": "\n\n".join(labels[6:]),
    }
    return detail


def matches_keywords(ann: Announcement, keywords: list) -> bool:
    """True if *any* keyword occurs in the announcement (case-insensitive).

    Matched against name, seat, category, state, court, register number and —
    when the detail was fetched — the full announcement text.
    """
    if not keywords:
        return True
    hay = " ".join(
        filter(
            None,
            [
                ann.name, ann.seat, ann.category, ann.state, ann.court,
                ann.register_num or "",
                (ann.detail or {}).get("text", ""),
            ],
        )
    ).lower()
    return any(kw.lower() in hay for kw in keywords)


class AnnouncementsPortal:
    """Search context for the portal's Registerbekanntmachungen section.

    ``search()`` opens a fresh session and keeps it so that ``fetch_detail()``
    can replay the PrimeFaces remote command against the same JSF view.
    """

    def __init__(self, delay: float = 3.0, timeout: int = 30):
        self.delay = delay
        self.timeout = timeout
        self._br = None
        self._html = None
        self._action = None
        self._first_request_done = False

    def _sleep(self):
        if self._first_request_done and self.delay:
            time.sleep(self.delay)
        self._first_request_done = True

    def search(
        self,
        date_from: str,
        date_to: str,
        land: str = "",
        court: str = "",
        seat: str = "",
        category: str = "",
    ) -> list[Announcement]:
        """Run the announcements search. Dates are ``DD.MM.YYYY`` strings."""
        self._sleep()
        br = _new_browser()
        br.open(BASE_URL, timeout=self.timeout)
        br.select_form(name="naviForm")
        br.form.new_control(
            "hidden", "naviForm:bekanntmachungenLink", {"value": "naviForm:bekanntmachungenLink"}
        )
        br.submit()
        br.select_form(name="bekanntMachungenForm")
        br["bekanntMachungenForm:datum_von_input"] = date_from
        br["bekanntMachungenForm:datum_bis_input"] = date_to
        if land:
            br["bekanntMachungenForm:land_input"] = [land]
        if court:
            br["bekanntMachungenForm:registergericht_input"] = [court]
        if seat:
            br["bekanntMachungenForm:sitz"] = seat
        if category:
            br["bekanntMachungenForm:kategorie_input"] = [category]
        br.form.new_control(
            "hidden", "bekanntMachungenForm:rrbSuche", {"value": "bekanntMachungenForm:rrbSuche"}
        )
        resp = br.submit()
        self._br = br
        self._action = br.geturl()
        self._html = resp.read().decode("utf-8", "replace")
        return parse_announcements(self._html)

    def fetch_detail(self, ann: Announcement) -> dict:
        """Fetch the full text of one announcement; stores it on ``ann.detail``."""
        if self._br is None:
            raise PortalError("call search() before fetch_detail()")
        self._sleep()
        source = parse_remote_source(self._html)
        vs = re.search(
            r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', self._html
        )
        if not vs:
            raise PortalError("no ViewState on announcements result page")
        data = {
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": source,
            "javax.faces.partial.execute": "bekanntMachungenForm",
            "javax.faces.partial.render": "bekanntMachungenForm",
            source: source,
            "bekanntMachungenForm": "bekanntMachungenForm",
            "javax.faces.ViewState": vs.group(1),
            "datum": ann.js_date,
            "id": ann.id,
        }
        req = mechanize.Request(
            self._action,
            urllib.parse.urlencode(data).encode(),
            {
                "Faces-Request": "partial/ajax",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
        )
        partial = self._br.open(req, timeout=self.timeout).read().decode("utf-8", "replace")
        if "einzelBekanntmachung" not in partial:
            raise PortalError(f"portal did not redirect to the announcement detail: {partial[:200]}")
        resp = self._br.open(
            BASE_URL + "/rp_web/einzelBekanntmachung/welcome.xhtml", timeout=self.timeout
        )
        ann.detail = parse_announcement_detail(resp.read().decode("utf-8", "replace"))
        return ann.detail
