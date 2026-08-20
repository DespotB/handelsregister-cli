"""Shared dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CompanyHit:
    """One row of the search result table."""

    index: int  # row index (data-ri) — used to address document links
    name: str
    court: str  # full court cell, e.g. "Berlin District court Berlin (Charlottenburg) HRB 261478"
    register_num: str | None  # e.g. "HRB 261478 B"
    state: str
    status: str  # e.g. "currently registered"
    doc_labels: list = field(default_factory=list)  # available links: AD, CD, HD, DK, UT, VÖ, SI

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "court": self.court,
            "register_num": self.register_num,
            "state": self.state,
            "status": self.status,
            "documents": self.doc_labels,
        }


@dataclass
class TreeNode:
    """A node of the DK document tree."""

    rowkey: str  # PrimeFaces rowkey, e.g. "0_0_2_1"
    label: str  # e.g. "Liste der Gesellschafter - Aufnahme in den Registerordner am 29.10.2024"
    leaf: bool  # leaves are downloadable documents


@dataclass
class Download:
    """A file that was saved to disk."""

    label: str  # human-readable document label
    path: Path
    size: int
    sha256: str
    source: str  # "direct:AD" | "dk:<rowkey>"

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "file": self.path.name,
            "size": self.size,
            "sha256": self.sha256,
            "source": self.source,
        }


@dataclass
class Announcement:
    """One Registerbekanntmachung from the portal's announcements search."""

    id: str  # portal-internal announcement id, e.g. "167692"
    date: str  # Bekanntmachungsdatum, "20.08.2026"
    js_date: str  # raw date string the portal's JS passes along, needed for detail fetch
    category: str  # e.g. "Löschungsankündigung"
    state: str  # Bundesland, e.g. "Bayern"
    court: str  # e.g. "Amtsgericht München"
    register_num: str | None  # e.g. "HRB 242458"
    name: str
    seat: str
    detail: dict | None = None  # filled by AnnouncementsPortal.fetch_detail()

    def as_dict(self) -> dict:
        d = {
            "id": self.id,
            "date": self.date,
            "category": self.category,
            "state": self.state,
            "court": self.court,
            "register_num": self.register_num,
            "name": self.name,
            "seat": self.seat,
        }
        if self.detail:
            d["detail"] = self.detail
        return d
